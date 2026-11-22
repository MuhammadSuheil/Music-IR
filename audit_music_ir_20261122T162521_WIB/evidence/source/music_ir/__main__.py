import argparse
import json
import sys
from pathlib import Path

from .data import ROOT, load_docs, prepare
from .engine import SearchEngine, load_config


def main():
    parser = argparse.ArgumentParser(description="Music IR: persiapan, pencarian, dan evaluasi")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--csv", type=Path, required=True)
    embed = sub.add_parser("embed")
    embed.add_argument("--batch-size", type=int, default=4)
    embed.add_argument("--local-files-only", action="store_true")
    sub.add_parser("index-elasticsearch")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--mode", choices=["AUTO", *[f"E{i}" for i in range(1, 6)]], default="AUTO",
                        help="AUTO menggabungkan retrieval, reranking, dan intent audio; E1–E5 untuk eksperimen.")
    search.add_argument("--backend", choices=["local", "elasticsearch"], default="local")
    search.add_argument("--trace", action="store_true", help="Sertakan jejak keputusan dan kontribusi skor.")
    search.add_argument("--inspect-track-id", help="Periksa lagu tertentu, termasuk yang gugur sebelum hasil akhir.")
    search.add_argument("--mood-basis", choices=["lyrics", "audio", "both"], help="Makna lirik, nuansa audio, atau keduanya untuk query mood AUTO.")
    draft = sub.add_parser("benchmark-draft")
    draft.add_argument("--output", type=Path, default=ROOT / "evaluation" / "queries.draft.jsonl")
    pool = sub.add_parser("benchmark-pool")
    pool.add_argument("--queries", type=Path, default=ROOT / "evaluation" / "queries.draft.jsonl")
    pool.add_argument("--directory", type=Path, default=ROOT / "artifacts" / "benchmark")
    pool.add_argument("--query-id", nargs="+")
    pool.add_argument("--split", choices=["dev", "test"])
    pool.add_argument("--depth", type=int, default=10)
    pool.add_argument("--modes", nargs="+", choices=["AUTO", *[f"E{i}" for i in range(1, 6)]])
    pool.add_argument("--backend", choices=["local", "elasticsearch"], default="local")
    export = sub.add_parser("benchmark-export")
    export.add_argument("--queries", type=Path, default=ROOT / "evaluation" / "queries.draft.jsonl")
    export.add_argument("--directory", type=Path, default=ROOT / "artifacts" / "benchmark")
    export.add_argument("--output", type=Path, default=ROOT / "artifacts" / "benchmark" / "export")
    export.add_argument("--split", choices=["dev", "test"], default="dev")
    export.add_argument("--query-id", nargs="+")
    evaluation = sub.add_parser("evaluate")
    evaluation.add_argument("--queries", required=True)
    evaluation.add_argument("--qrels", required=True)
    evaluation.add_argument("--output", default="artifacts/evaluation")
    evaluation.add_argument("--modes", nargs="+", choices=["AUTO", *[f"E{i}" for i in range(1, 6)]], default=["E1", "E2"])
    evaluation.add_argument("--backend", choices=["local", "elasticsearch"], default="local")
    evaluation.add_argument("--split", choices=["dev", "test"], default="test")
    evaluation.add_argument("--repeats", type=int, default=5)
    tuning = sub.add_parser("tune")
    tuning.add_argument("--queries", required=True)
    tuning.add_argument("--qrels", required=True)
    tuning.add_argument("--output", default="artifacts/tuning")
    tuning.add_argument("--backend", choices=["local", "elasticsearch"], default="local")
    tuning.add_argument("--lexical-only", action="store_true")
    args = parser.parse_args()
    if args.command == "prepare":
        result = prepare(args.csv)
    elif args.command == "embed":
        from .semantic import build_embeddings
        result = build_embeddings(load_docs(), load_config(), args.batch_size, args.local_files_only)
    elif args.command == "index-elasticsearch":
        from .lexical import ElasticsearchBM25
        result = {"index": ElasticsearchBM25(load_docs(), load_config()).build()}
    elif args.command == "evaluate":
        from .evaluate import evaluate
        result = evaluate(SearchEngine(backend=args.backend), args.queries, args.qrels, args.output, args.modes, args.split, args.repeats)
    elif args.command == "tune":
        from .tune import tune
        result = tune(SearchEngine(backend=args.backend), args.queries, args.qrels, args.output, args.lexical_only)
    elif args.command == "benchmark-draft":
        from .benchmark import draft_queries
        if args.output.exists():
            raise FileExistsError("Draft sudah ada; pilih --output lain agar koreksi manusia tidak tertimpa.")
        rows = draft_queries(load_docs())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("\n".join(json.dumps(q, ensure_ascii=False) for q in rows) + "\n", encoding="utf-8")
        result = {"queries": len(rows), "path": str(args.output), "labels_generated": 0, "review_status": "draft"}
    elif args.command == "benchmark-pool":
        from .benchmark import BenchmarkStore
        engine = SearchEngine(backend=args.backend)
        store = BenchmarkStore(engine.docs, args.queries, args.directory)
        selected = [q for q in store.queries() if (not args.query_id or q["query_id"] in args.query_id)
                    and (not args.split or q["split"] == args.split)]
        if not selected or args.query_id and set(args.query_id) != {q["query_id"] for q in selected}:
            raise ValueError("Pilihan query/split tidak valid.")
        result = []
        for query in selected:
            row = store.prepare_pool(engine, query["query_id"], args.modes, args.depth)
            result.append(row)
            print(json.dumps(row), flush=True)
    elif args.command == "benchmark-export":
        from .benchmark import BenchmarkStore
        bundle = BenchmarkStore(load_docs(), args.queries, args.directory).export(args.split, args.query_id)
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "queries.jsonl").write_text(bundle["queries_jsonl"], encoding="utf-8")
        (args.output / "qrels.csv").write_text(bundle["qrels_csv"], encoding="utf-8")
        (args.output / "manifest.json").write_text(json.dumps(bundle["manifest"], indent=2), encoding="utf-8")
        result = {"output": str(args.output), **bundle["manifest"]}
    else:
        result = SearchEngine(backend=args.backend).search(args.query, args.mode,
                    trace=args.trace or bool(args.inspect_track_id), inspect_track_id=args.inspect_track_id, mood_basis=args.mood_basis)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
