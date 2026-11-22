"""Evaluation on human judgments. No synthetic semantic labels are generated."""
import csv
import json
import math
import random
import statistics
import hashlib
import platform
from datetime import datetime, timezone
from importlib.metadata import version
from collections import defaultdict
from pathlib import Path

from .data import corpus_hash


def metrics(ranking, labels):
    relevant = {key for key, grade in labels.items() if grade >= 2}
    dcg = sum((2 ** labels.get(key, 0) - 1) / math.log2(i + 2) for i, key in enumerate(ranking[:10]))
    ideal = sum((2 ** grade - 1) / math.log2(i + 2) for i, grade in enumerate(sorted(labels.values(), reverse=True)[:10]))
    return {"ndcg@10": dcg / ideal if ideal else 0,
            "mrr@10": next((1 / (i + 1) for i, key in enumerate(ranking[:10]) if key in relevant), 0),
            "recall@100": len(set(ranking[:100]) & relevant) / len(relevant) if relevant else 0}


def read_benchmark(queries_path, qrels_path, docs, required_split=None):
    queries = [json.loads(line) for line in Path(queries_path).read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = [q["query_id"] for q in queries]
    if len(ids) != len(set(ids)):
        raise ValueError("query_id berulang.")
    track_ids = {d["track_id"] for d in docs}
    labels = defaultdict(dict)
    with Path(qrels_path).open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            qid, track_id, grade = row["query_id"], row["track_id"], int(row["relevance"])
            if qid not in ids or track_id not in track_ids or grade not in range(4):
                raise ValueError("Qrels memiliki ID/label yang tidak valid.")
            if track_id in labels[qid] and labels[qid][track_id] != grade:
                raise ValueError("Konflik penilai harus diselesaikan sebelum evaluasi.")
            labels[qid][track_id] = grade
    for q in queries:
        if q.get("split") not in {"dev", "test"}:
            raise ValueError("Setiap query harus memiliki split dev atau test.")
        required = required_split is None or q["split"] == required_split
        if required and q.get("review_status", "approved") != "approved":
            raise ValueError(f"Tinjau dan setujui draft query dahulu: {q['query_id']}")
        if required and not any(v >= 2 for v in labels[q["query_id"]].values()):
            raise ValueError(f"Audit query tanpa label relevan dahulu: {q['query_id']}")
    groups = defaultdict(set)
    for q in queries:
        groups[q.get("group_id", q["query_id"])].add(q["split"])
    if any(len(splits) > 1 for splits in groups.values()):
        raise ValueError("group_id yang sama muncul di development dan test.")
    return queries, labels


def evaluate(engine, queries_path, qrels_path, output, modes, split="test", repeats=5):
    queries, labels = read_benchmark(queries_path, qrels_path, engine.docs, required_split=split)
    queries = [q for q in queries if q["split"] == split]
    if not queries or repeats < 1:
        raise ValueError("Split harus memiliki query dan repeats harus positif.")
    if any(m in {"AUTO", "E3", "E4", "E5"} for m in modes):
        engine.semantic.warmup()
    for i in range(10):
        engine.search(queries[i % len(queries)]["query"], modes[i % len(modes)], 100)
    jobs = [(q, mode, repeat) for q in queries for mode in modes for repeat in range(repeats)]
    random.Random(42).shuffle(jobs)
    runs = []
    candidate_checks = {}
    for q, mode, repeat in jobs:
        result = engine.search(q["query"], mode, 100)
        if mode == "AUTO" and result.get("pipeline", {}).get("degraded"):
            raise RuntimeError("Evaluasi AUTO dihentikan: semantik gagal dan hasil fallback tidak boleh dianggap run penuh.")
        ranking = [song["track_id"] for song in result["results"]]
        runs.append({"query_id": q["query_id"], "category": q["category"], "mode": mode,
                     "repeat": repeat, "latency_ms": result["latency_ms"],
                     **metrics(ranking, labels[q["query_id"]]), "ranking": ranking,
                     "judged@10": sum(track_id in labels[q["query_id"]] for track_id in ranking[:10]) / max(1, len(ranking[:10])),
                     "unjudged_top10": [track_id for track_id in ranking[:10] if track_id not in labels[q["query_id"]]],
                     "query_type": result.get("query_type"), "pipeline": result.get("pipeline")})
        if mode in {"E3", "E4"}:
            key = (q["query_id"], repeat)
            candidates = set(result["candidate_ids"])
            if key in candidate_checks and candidate_checks[key] != candidates:
                raise AssertionError("E3 dan E4 harus memakai himpunan kandidat identik.")
            candidate_checks[key] = candidates
    summary = {}
    import numpy as np
    for mode in modes:
        by_mode = [r for r in runs if r["mode"] == mode]
        summary[mode] = {}
        for category in ["all", *sorted({r["category"] for r in by_mode})]:
            selected = [r for r in by_mode if category == "all" or r["category"] == category]
            summary[mode][category] = {metric: statistics.mean(r[metric] for r in selected) for metric in ("ndcg@10", "mrr@10", "recall@100", "judged@10")}
            summary[mode][category].update(latency_median_ms=statistics.median(r["latency_ms"] for r in selected), latency_p95_ms=float(np.percentile([r["latency_ms"] for r in selected], 95)))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "runs.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in runs) + "\n", encoding="utf-8")
    from .diagnostics import implementation_hash
    manifest = {"backend": engine.backend, "config": engine.config, "corpus_sha256": corpus_hash(engine.docs),
                "implementation_sha256": implementation_hash(),
                "created_utc": datetime.now(timezone.utc).isoformat(),
                "queries_sha256": hashlib.sha256(Path(queries_path).read_bytes()).hexdigest(),
                "qrels_sha256": hashlib.sha256(Path(qrels_path).read_bytes()).hexdigest(),
                "python": platform.python_version(), "platform": platform.platform(),
                "packages": {name: version(name) for name in ("numpy", "fastapi", "uvicorn")},
                "split": split, "seed": 42, "repeats": repeats, "warmup_queries": 10,
                "judgment_policy": "unjudged=0; recall relative to known qrels", "summary": summary}
    (output / "summary.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return summary
