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
