"""Versioned relevance runs: frozen retrieval, provisional LLM labels, explicit human review.

This module never modifies retrieval configuration or the legacy benchmark store.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sqlite3
import statistics
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .data import ROOT, corpus_hash, load_docs
from .diagnostics import implementation_hash
from .engine import SearchEngine, load_config
from .evaluate import metrics

RUNS = ROOT / "artifacts" / "relevance"
MODES = ("E1", "E2", "E3", "E4", "E5", "AUTO")


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + "." + str(os.getpid()) + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


@contextmanager
def work_lock(directory):
    """OS releases this lock after a crash; a stale pathname never prevents resume."""
    path = Path(directory) / ".work.lock"
    with path.open("a+b") as handle:
        if path.stat().st_size == 0:
            handle.write(b"0"); handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Run ini sedang dikerjakan proses lain.") from exc
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class RelevanceRun:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
        self.queries = json.loads((self.directory / "queries.json").read_text(encoding="utf-8"))
        self.docs = json.loads((self.directory / "corpus.json").read_text(encoding="utf-8"))
        self.by_query = {q["query_id"]: q for q in self.queries}
        self.by_track = {d["track_id"]: d for d in self.docs}
        if (digest(self.queries) != self.manifest["queries_sha256"] or
                corpus_hash(self.docs) != self.manifest["corpus_sha256"] or
                digest(self.manifest["config"]) != self.manifest["config_sha256"]):
            raise ValueError("Snapshot run berubah. Buat run/versi baru; jangan mencampur label.")

    @classmethod
    def create(cls, directory, docs=None, queries=None, config=None, backend="local"):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False)
        docs = load_docs() if docs is None else docs
        config = load_config() if config is None else config
        if queries is None:
            queries = [json.loads(x) for x in (ROOT / "evaluation/queries.draft.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        if not queries or len({q["query_id"] for q in queries}) != len(queries):
            raise ValueError("Daftar query kosong atau ID berulang.")
        if len({d['track_id'] for d in docs}) != len(docs):
            raise ValueError("Corpus memiliki ID berulang.")
        groups = {}
        for q in queries:
            if q.get('split') not in {'dev', 'test'} or not q.get('group_id') or not q.get('intent_note'):
                raise ValueError('Setiap query memerlukan split, group_id, dan intent_note.')
            if q['group_id'] in groups and groups[q['group_id']] != q['split']:
                raise ValueError('Group melintasi split.')
            groups[q['group_id']] = q['split']
        from importlib.metadata import version
        manifest = {"schema": 1, "run_id": directory.name, "created_utc": now(),
                    "corpus_sha256": corpus_hash(docs), "queries_sha256": digest(queries),
                    "config": config, "config_sha256": digest(config), "backend": backend,
                    "implementation_sha256": implementation_hash(), "modes": list(MODES), "pool_depth": 100,
                    "ranking_object": "primary_results", "query_count": len(queries), "document_count": len(docs),
                    "query_need_origin": "existing authored/corpus draft; not human-approved; no LLM rewrite",
                    "python": sys.version, "packages": {p: version(p) for p in ['numpy', 'fastapi', 'pandas']},
                    "human_review_policy": "Explicit pair and query decisions only; no automatic approval; changed definitions require new run",
                    "prior_audit": {"queries_draft": 160, "initial_pool_pairs": 191, "initial_pool_queries": 10, "historical_not_this_run": True}}
        atomic_json(directory / "manifest.json", manifest)
        atomic_json(directory / "queries.json", queries)
        atomic_json(directory / "corpus.json", docs)
        run = cls(directory)
        with run.connect():
            pass
        return run

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.directory / "state.sqlite3", timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
          CREATE TABLE IF NOT EXISTS rankings(query_id TEXT, mode TEXT, status TEXT, response TEXT, error TEXT, updated TEXT,
            PRIMARY KEY(query_id,mode));
          CREATE TABLE IF NOT EXISTS pairs(query_id TEXT, track_id TEXT, PRIMARY KEY(query_id,track_id));
          CREATE TABLE IF NOT EXISTS auto_labels(query_id TEXT, track_id TEXT, cache_key TEXT, status TEXT, label TEXT, updated TEXT,
            PRIMARY KEY(query_id,track_id));
          CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, query_id TEXT, track_id TEXT, created TEXT, status TEXT, detail TEXT);
          CREATE TABLE IF NOT EXISTS reviews(query_id TEXT, track_id TEXT, reviewer_id TEXT, human_grade INTEGER,
            human_review_status TEXT, final_grade INTEGER, reason TEXT, viewed_auto INTEGER, independent_grade INTEGER, updated TEXT,
            PRIMARY KEY(query_id,track_id));
          CREATE TABLE IF NOT EXISTS review_history(id INTEGER PRIMARY KEY, kind TEXT, query_id TEXT, track_id TEXT,
            reviewer_id TEXT, created TEXT, payload TEXT);
          CREATE TABLE IF NOT EXISTS exposures(query_id TEXT, track_id TEXT, reviewer_id TEXT, created TEXT,
            PRIMARY KEY(query_id,track_id,reviewer_id));
          CREATE TABLE IF NOT EXISTS query_reviews(query_id TEXT PRIMARY KEY, reviewer_id TEXT, approved INTEGER, notes TEXT, updated TEXT);
          CREATE TABLE IF NOT EXISTS drafts(query_id TEXT, track_id TEXT, reviewer_id TEXT, body TEXT, updated TEXT,
            PRIMARY KEY(query_id,track_id,reviewer_id));
        """)
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def prepare(self, engine=None, progress=print):
        engine = engine or SearchEngine(docs=self.docs, config=self.manifest["config"], backend=self.manifest["backend"])
        if (corpus_hash(engine.docs) != self.manifest["corpus_sha256"] or digest(engine.config) != self.manifest["config_sha256"] or
                implementation_hash() != self.manifest["implementation_sha256"]):
            raise ValueError("Pipeline/config/corpus berbeda dari run yang dibekukan.")
        with work_lock(self.directory):
            for q in self.queries:
                for mode in self.manifest['modes']:
                    with self.connect() as db:
                        saved = db.execute("SELECT status FROM rankings WHERE query_id=? AND mode=?", (q['query_id'], mode)).fetchone()
                    if saved and saved['status'] == 'ok':
                        continue
                    try:
                        response = engine.search(q['query'], mode, 100)
                        if response.get('pipeline', {}).get('degraded'):
                            raise RuntimeError('Run penuh menolak fallback/degraded: ' + '; '.join(response.get('warnings', [])))
                        ids = [x['track_id'] for x in response['results']]
                        if len(ids) != len(set(ids)) or any(t not in self.by_track for t in ids):
                            raise ValueError('Ranking berisi ID tidak valid/berulang.')
                        # No hint IDs and no random negatives are added to this evaluation pool.
                        record = {'ranking': ids, 'length': len(ids), 'pipeline': response.get('pipeline'),
                                  'query_type': response.get('query_type'), 'latency_ms': response.get('latency_ms'),
                                  'related_count_excluded': len(response.get('related_results', []))}
                        with self.connect() as db:
                            db.execute("INSERT OR REPLACE INTO rankings VALUES (?,?,?,?,?,?)", (q['query_id'], mode, 'ok', json.dumps(record), None, now()))
                            db.executemany("INSERT OR IGNORE INTO pairs VALUES (?,?)", [(q['query_id'], t) for t in ids])
                    except Exception as exc:
                        with self.connect() as db:
                            db.execute("INSERT OR REPLACE INTO rankings VALUES (?,?,?,?,?,?)", (q['query_id'], mode, 'error', None, str(exc), now()))
                        with (self.directory / 'failures.jsonl').open('a', encoding='utf-8') as f:
                            f.write(json.dumps({'phase': 'pool', 'query_id': q['query_id'], 'mode': mode, 'error': str(exc), 'time': now()})+'\n')
                    progress(json.dumps({'phase': 'pool', 'query_id': q['query_id'], 'mode': mode, **self.counts()}, ensure_ascii=False), flush=True)
                atomic_json(self.directory / 'progress.json', self.counts())
            self.export_rankings()
        return self.counts()

    def counts(self):
        with self.connect() as db:
            counts = {r['status']: r['n'] for r in db.execute('SELECT status,COUNT(*) AS n FROM rankings GROUP BY status')}
            pairs = db.execute('SELECT COUNT(*) FROM pairs').fetchone()[0]
            auto = {r['status']: r['n'] for r in db.execute('SELECT status,COUNT(*) AS n FROM auto_labels GROUP BY status')}
            final = db.execute('SELECT COUNT(*) FROM reviews WHERE final_grade IS NOT NULL').fetchone()[0]
            reviewed_queries = db.execute('SELECT COUNT(*) FROM query_reviews WHERE approved=1').fetchone()[0]
        expected = len(self.queries) * len(self.manifest['modes'])
        return {'run_id': self.directory.name, 'query_count': len(self.queries), 'ranking_jobs_expected': expected,
                'ranking_jobs_completed': counts.get('ok', 0), 'ranking_errors': counts.get('error', 0),
                'pool_complete': counts.get('ok', 0) == expected, 'pairs': pairs,
                'auto_completed': auto.get('ok', 0), 'auto_needs_review': auto.get('needs_review', 0), 'auto_errors': auto.get('error', 0),
                'auto_unprocessed': pairs - sum(auto.values()), 'auto_processed': sum(auto.values()),
                'auto_complete': pairs > 0 and sum(auto.values()) == pairs and counts.get('ok', 0) == expected,
                'auto_labels_resolved': pairs > 0 and auto.get('ok', 0) == pairs and counts.get('ok', 0) == expected,
                'human_final_pairs': final, 'query_definitions_approved': reviewed_queries,
                'human_complete': pairs > 0 and final == pairs and reviewed_queries == len(self.queries) and counts.get('ok', 0) == expected}

    def export_rankings(self):
        with self.connect() as db, (self.directory / 'rankings.jsonl').open('w', encoding='utf-8') as f:
            for r in db.execute('SELECT * FROM rankings ORDER BY query_id,mode'):
                row = dict(r);row['response'] = json.loads(row['response']) if row['response'] else None
                f.write(json.dumps(row, ensure_ascii=False)+'\n')

    def pair_ids(self, query_id=None):
        with self.connect() as db:
            sql = 'SELECT query_id,track_id FROM pairs';args = []
            if query_id:
                sql += ' WHERE query_id=?'; args = [query_id]
            return [tuple(r) for r in db.execute(sql+' ORDER BY query_id,track_id', args)]


def discover_backends():
    """Read configured names/flags and loopback model inventories; never export secrets."""
    import urllib.request
    probes = []
    for base, path in [('http://127.0.0.1:11434', '/api/tags'), ('http://127.0.0.1:1234', '/v1/models'), ('http://127.0.0.1:8001', '/v1/models')]:
        try:
            with urllib.request.urlopen(base+path, timeout=2) as f:
                data = json.load(f)
            probes.append({'base_url': base, 'models': data, 'available': True})
        except Exception as exc:
            probes.append({'base_url': base, 'available': False, 'error_type': type(exc).__name__})
    return {'checked_utc': now(), 'configured_provider': os.environ.get('MUSIC_IR_JUDGE_PROVIDER'),
            'configured_model': os.environ.get('MUSIC_IR_JUDGE_MODEL'),
            'configured_base_url_present': bool(os.environ.get('MUSIC_IR_JUDGE_BASE_URL')),
            'credential_presence_only': {k: bool(os.environ.get(k)) for k in ['MUSIC_IR_JUDGE_API_KEY', 'OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'GROQ_API_KEY', 'ANTHROPIC_API_KEY']},
            'local_probes': probes,
            'embedding_model_is_not_an_instruction_llm': 'BAAI/bge-m3',
            'assistant_session': 'Direct Codex session judgments can be imported with recorded session provenance; no callable batch API is inferred from subscription/session credentials.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init'); init.add_argument('--run', type=Path, required=True)
    probe = sub.add_parser('discover'); probe.add_argument('--output', type=Path)
    for name in ['pool', 'label', 'export', 'report', 'packet', 'import-session', 'clone-for-judge']:
        p = sub.add_parser(name);p.add_argument('--run', required=True, type=Path)
        if name=='label':p.add_argument('--smoke', action='store_true');p.add_argument('--retry-errors', action='store_true')
        if name=='packet':p.add_argument('--limit', type=int, default=5);p.add_argument('--query-id');p.add_argument('--output',type=Path,required=True)
        if name=='import-session':p.add_argument('--input', type=Path, required=True)
        if name=='clone-for-judge':p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command=='init':result = RelevanceRun.create(args.run).counts()
    elif args.command=='discover':
        result = discover_backends()
        if args.output:atomic_json(args.output, result)
    else:
        run = RelevanceRun(args.run)
        if args.command=='pool':result = run.prepare()
        else:
            from .relevance_judge import batch_label, session_packet, import_session
            from .relevance_review import export_run, write_report, clone_for_judge
            if args.command=='label':result = batch_label(run, smoke=args.smoke, retry_errors=args.retry_errors)
            elif args.command=='packet':result = session_packet(run, args.output, args.limit, args.query_id)
            elif args.command=='import-session':result = import_session(run, args.input)
            elif args.command=='export':result = export_run(run)
            elif args.command=='report':result = write_report(run)
            elif args.command=='clone-for-judge':result = clone_for_judge(run,args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if isinstance(result,dict) and result.get('status')=='blocked_backend':raise SystemExit(2)


if __name__=='__main__':
    if hasattr(sys.stdout, 'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
