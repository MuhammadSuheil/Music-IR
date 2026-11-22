"""Select weights using only development judgments, without training the encoder."""
import itertools
import json
from pathlib import Path

import numpy as np

from .audio import parse
from .evaluate import metrics, read_benchmark


def weight_grid():
    return [tuple(v / 4 for v in values) for values in itertools.product(range(5), repeat=5) if sum(values) == 4]


def trace_ranking(trace, weights, audio_weight=0):
    ids = trace["track_ids"]
    if not ids:
        return []
    text = np.asarray(trace["features"]) @ weights if trace["has_text"] else np.zeros(len(ids))
    weight = (audio_weight if trace["has_text"] else 1) if trace["has_audio"] else 0
    scores = (1 - weight) * text + weight * np.asarray(trace["audio"])
    order = sorted(range(len(ids)), key=lambda i: (-float(scores[i]), -trace["rrf"][i], ids[i]))
    return [ids[i] for i in order]


def tune(engine, queries_path, qrels_path, output, lexical_only=False):
    queries, labels = read_benchmark(queries_path, qrels_path, engine.docs, required_split="dev")
    dev = [q for q in queries if q["split"] == "dev"]
    text_dev = [q for q in dev if parse(q["query"]).text and not parse(q["query"]).active]
    audio_dev = [q for q in dev if parse(q["query"]).active]
    if not text_dev:
        raise ValueError("Sediakan query development teks dengan qrels sebelum tuning.")
    history = {"field_trials": [], "text_trials": [], "audio_trials": []}
    best_score, best_fields = -1, None
    for weights in [(1, 1, 1), (2, 1, 1), (2, 2, 1), (3, 2, 1)]:
        engine.config["field_weights"] = list(weights)
        scores = []
        for q in text_dev:
            response = engine.search(q["query"], "E2", 100)
            scores.append(metrics(response["candidate_ids"], labels[q["query_id"]])["ndcg@10"])
        score = float(np.mean(scores))
        history["field_trials"].append({"weights": weights, "ndcg@10": score})
        if score > best_score:
            best_score, best_fields = score, weights
    engine.config["field_weights"] = list(best_fields)
    if not lexical_only:
        cached = [(q, engine.search(q["query"], "E4", 100, trace=True)["trace"]) for q in text_dev]
        best_score, best_text = -1, None
        for weights in weight_grid():
            score = float(np.mean([metrics(trace_ranking(trace, weights), labels[q["query_id"]])["ndcg@10"] for q, trace in cached]))
            history["text_trials"].append({"weights": weights, "ndcg@10": score})
            if score > best_score:
                best_score, best_text = score, weights
        engine.config["text_weights"] = list(best_text)
        if audio_dev:
            cached = [(q, engine.search(q["query"], "E5", 100, trace=True)["trace"]) for q in audio_dev]
            best_score, best_audio = -1, None
            for weight in [.25, .5, .75]:
                score = float(np.mean([metrics(trace_ranking(trace, best_text, weight), labels[q["query_id"]])["ndcg@10"] for q, trace in cached]))
                history["audio_trials"].append({"weight": weight, "ndcg@10": score})
                if score > best_score:
                    best_score, best_audio = score, weight
            engine.config["audio_weight"] = best_audio
    # Full tuning is marked complete only when audio dev judgments also exist.
    engine.config["tuned"] = not lexical_only and bool(audio_dev)
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    (target / "config.json").write_text(json.dumps(engine.config, indent=2), encoding="utf-8")
    (target / "trials.json").write_text(json.dumps({"selection_split": "dev", "query_ids": [q["query_id"] for q in dev],
                                                 "backend": engine.backend, "tie_policy": "first trial in documented grid order", **history}, indent=2), encoding="utf-8")
    return {"config_path": str(target / "config.json"), "trials_path": str(target / "trials.json"), "config": engine.config}
