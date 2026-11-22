import os
from typing import Literal
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .engine import SearchEngine
from .catalog import catalog, track_summary
from .benchmark import BenchmarkStore


@asynccontextmanager
async def lifespan(app):
    app.state.engine = SearchEngine(backend=os.environ.get("MUSIC_IR_BACKEND", "local"))
    yield


app = FastAPI(title="Music IR", version="0.2.0", lifespan=lifespan)


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: str = Field(default="AUTO", pattern="^(AUTO|E[1-5])$")
    top_k: int = Field(default=10, ge=1, le=100)
    trace: bool = False
    inspect_track_id: str | None = Field(default=None, min_length=1, max_length=100)
    mood_basis: Literal["lyrics", "audio", "both"] | None = None


class PoolRequest(BaseModel):
    modes: list[str] | None = None
    depth: int = Field(default=10, ge=1, le=100)


class ReviewRequest(BaseModel):
    annotator: str = Field(min_length=1, max_length=64)


class JudgmentRequest(ReviewRequest):
    track_id: str = Field(min_length=1, max_length=100)
    grade: int = Field(ge=0, le=3, strict=True)
    notes: str = Field(default="", max_length=2000)


def benchmark_store():
    engine = app.state.engine
    if not hasattr(engine, "benchmark_store"):
        engine.benchmark_store = BenchmarkStore(engine.docs)
    return engine.benchmark_store


def benchmark_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (RuntimeError, OSError, ImportError) as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/benchmark")
def get_benchmark():
    return benchmark_call(benchmark_store().summary)


@app.get("/benchmark/export")
def export_benchmark(split: str = "dev", query_id: str | None = None):
    return benchmark_call(benchmark_store().export, split, [query_id] if query_id else None)


@app.get("/benchmark/queries/{query_id}")
def get_benchmark_candidates(query_id: str, annotator: str = ""):
    return benchmark_call(benchmark_store().candidates, query_id, annotator)


@app.post("/benchmark/queries/{query_id}/pool")
def prepare_benchmark_pool(query_id: str, request: PoolRequest):
    return benchmark_call(benchmark_store().prepare_pool, app.state.engine, query_id, request.modes, request.depth)


@app.put("/benchmark/queries/{query_id}/review")
def review_benchmark_query(query_id: str, request: ReviewRequest):
    return benchmark_call(benchmark_store().review, query_id, request.annotator)


@app.put("/benchmark/queries/{query_id}/judgments")
def judge_benchmark_candidate(query_id: str, request: JudgmentRequest):
    return benchmark_call(benchmark_store().judge, query_id, request.track_id, request.annotator, request.grade, request.notes)


@app.get("/health")
def health():
    return app.state.engine.status()


@app.get("/catalog")
def get_catalog(limit: int = Query(default=60, ge=1, le=100), offset: int = Query(default=0, ge=0),
                genre: str | None = None):
    return catalog(app.state.engine.docs, limit, offset, genre)


@app.get("/tracks/{track_id}")
def get_track(track_id: str):
    doc = next((d for d in app.state.engine.docs if d["track_id"] == track_id), None)
    if doc is None:
        raise HTTPException(404, "Lagu tidak ditemukan dalam koleksi.")
    return {**track_summary(doc), "lyrics": doc.get("lyrics", "")}


@app.post("/search")
def search(request: SearchRequest):
    try:
        return app.state.engine.search(request.query, request.mode, request.top_k,
                                       trace=request.trace or request.inspect_track_id is not None,
                                       inspect_track_id=request.inspect_track_id, mood_basis=request.mood_basis)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (RuntimeError, OSError, ImportError) as exc:
        raise HTTPException(503, str(exc)) from exc


# Relevance evaluation is a separate store; search/ranking and legacy judgments are unchanged.
class RelevanceActor(BaseModel):
    reviewer_id: str = Field(min_length=1, max_length=64)


class RelevanceQueryReview(RelevanceActor):
    approved: bool = Field(strict=True)
    notes: str = Field(default='', max_length=4000)


class RelevanceDraft(RelevanceActor):
    grade: int | None = Field(default=None, ge=0, le=3, strict=True)
    reason: str = Field(default='', max_length=4000)


class RelevanceDecision(RelevanceDraft):
    action: Literal['independent', 'accept', 'correct', 'flag']
    expected_updated: str | None = None


class RelevanceRevision(RelevanceActor):
    query: str = Field(min_length=1, max_length=2000)
    user_need: str = Field(min_length=1, max_length=4000)
    reason: str = Field(min_length=1, max_length=4000)


def relevance_run(run_id):
    from .relevance_review import open_run
    return open_run(run_id)


@app.get('/relevance/runs')
def relevance_runs():
    from .relevance_review import runs_summary
    return benchmark_call(runs_summary)


@app.get('/relevance/runs/{run_id}')
def relevance_summary(run_id: str):
    from .relevance_review import run_summary
    return benchmark_call(lambda: run_summary(relevance_run(run_id)))


@app.get('/relevance/runs/{run_id}/queries/{query_id}')
def relevance_candidates(run_id: str, query_id: str, reviewer_id: str = '',
                         offset: int = Query(default=0, ge=0), limit: int = Query(default=1, ge=1, le=20)):
    from .relevance_review import query_candidates
    return benchmark_call(lambda: query_candidates(relevance_run(run_id), query_id, reviewer_id, offset, limit))


@app.put('/relevance/runs/{run_id}/queries/{query_id}/definition')
def relevance_definition(run_id: str, query_id: str, request: RelevanceQueryReview):
    from .relevance_review import approve_query
    return benchmark_call(lambda: approve_query(relevance_run(run_id), query_id, request.reviewer_id, request.approved, request.notes))


@app.post('/relevance/runs/{run_id}/queries/{query_id}/revision')
def relevance_revision(run_id: str, query_id: str, request: RelevanceRevision):
    from .relevance_review import fork_query
    return benchmark_call(lambda: fork_query(relevance_run(run_id), query_id, request.reviewer_id, request.query, request.user_need, request.reason))


@app.post('/relevance/runs/{run_id}/queries/{query_id}/tracks/{track_id}/proposal')
def relevance_proposal(run_id: str, query_id: str, track_id: str, request: RelevanceActor):
    from .relevance_review import reveal_auto
    return benchmark_call(lambda: reveal_auto(relevance_run(run_id), query_id, track_id, request.reviewer_id))


@app.put('/relevance/runs/{run_id}/queries/{query_id}/tracks/{track_id}/draft')
def relevance_draft(run_id: str, query_id: str, track_id: str, request: RelevanceDraft):
    from .relevance_review import save_draft
    return benchmark_call(lambda: save_draft(relevance_run(run_id), query_id, track_id, request.reviewer_id, request.grade, request.reason))


@app.put('/relevance/runs/{run_id}/queries/{query_id}/tracks/{track_id}/review')
def relevance_review(run_id: str, query_id: str, track_id: str, request: RelevanceDecision):
    from .relevance_review import save_review
    return benchmark_call(lambda: save_review(relevance_run(run_id), query_id, track_id, request.reviewer_id,
                                            request.action, request.grade, request.reason, request.expected_updated))


@app.post('/relevance/runs/{run_id}/export')
def relevance_export(run_id: str):
    from .relevance_review import write_report
    return benchmark_call(lambda: write_report(relevance_run(run_id)))


@app.get('/relevance/runs/{run_id}/export')
def relevance_export_file(run_id: str, name: str):
    from fastapi.responses import FileResponse
    from .relevance_review import open_run
    allowed={'qrels_auto.tsv','qrels_final.tsv','metrics_auto_summary.json','metrics_final_summary.json',
             'metrics_auto_per_query.csv','metrics_final_per_query.csv','comparison.json','human_review_history.jsonl',
             'auto_labels.jsonl','unresolved_pairs.csv','LAPORAN_EVALUASI_RELEVANSI.md','TEKS_SIAP_LAPORAN.md'}
    def resolve():
        if name not in allowed:raise ValueError('File ekspor tidak diizinkan.')
        run=open_run(run_id)
        import json
        pointer=run.directory/'latest_export.json'
        if not pointer.exists():raise KeyError('Buat ekspor terlebih dahulu.')
        latest=json.loads(pointer.read_text(encoding='utf-8'))
        path=(run.directory/latest['directory']/name).resolve()
        if name=='TEKS_SIAP_LAPORAN.md':path=run.directory/name
        if not path.is_relative_to((run.directory/'exports').resolve()) and name!='TEKS_SIAP_LAPORAN.md':raise ValueError('Path ekspor tidak valid.')
        if not path.exists():raise KeyError('Belum ada query yang seluruh poolnya selesai direview; qrels final belum tersedia.')
        return FileResponse(path,filename=name)
    return benchmark_call(resolve)
