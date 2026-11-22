"""Opt-in explanations of the actual retrieval and ranking decisions."""
import hashlib
import json
import math
from pathlib import Path

from .data import corpus_hash

FEATURE_NAMES = ("bm25_normalized", "cosine_normalized", "title_overlap", "artist_overlap", "lyric_phrase")


def implementation_hash():
    digest = hashlib.sha256()
    for name in ("engine.py", "query.py", "lyrics.py", "audio.py", "lexical.py", "semantic.py", "mood.py", "metadata.py", "passages.py"):
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


def explain(engine, *, response, rankings, retrieved, before, bm, cosine, mask, audio, fusion,
            features, weights, text_score, audio_weight, bonuses, final, lyric_matches, inspect_track_id,
            timings, planned_kind, metadata_mask, theme_evidence, theme_mix, passage_stats):
    source_ranks = {name: {i: rank for rank, i in enumerate(ranking, 1)} for name, ranking in rankings.items()}
    before_ranks = {i: rank for rank, i in enumerate(before, 1)}
    final_ranks = {track_id: rank for rank, track_id in enumerate(response["candidate_ids"], 1)}
    positions = {doc["track_id"]: i for i, doc in enumerate(engine.docs)}
    inspected = positions.get(inspect_track_id)
    included = set(retrieved)
    if inspected is not None:
        included.add(inspected)
    rows = []
    displayed = {r["track_id"] for r in response["results"]}
    related = {r["track_id"] for r in response.get("related_results", [])}
    for i in sorted(included, key=lambda i: (final_ranks.get(engine.docs[i]["track_id"], 100000),
                                             before_ranks.get(i, 100000), -float(fusion[i]), engine.docs[i]["track_id"])):
        doc = engine.docs[i]
        track_id = doc["track_id"]
        rank = final_ranks.get(track_id)
        if response["pipeline"]["audio"] and not mask[i]:
            disposition = "audio_filtered"
        elif not metadata_mask[i]:
            disposition = "intent_filtered"
        elif rank is not None:
            disposition = "ranked"
        elif i in retrieved:
            disposition = "candidate_limit"
        else:
            disposition = "not_retrieved"
        available = features is not None and i in before_ranks
        values = {name: float(feature[i]) for name, feature in zip(FEATURE_NAMES, features)} if available else {}
        contributions = {}
        if rank is not None:
            if response["mode"] in {"E1", "E2"}:
                contributions = {"bm25_raw": float(bm[i])}
            elif response["mode"] == "E3":
                contributions = {"rrf": float(fusion[i])}
            else:
                if response.get("catalog_match"):
                    contributions = {"metadata_match": (1 - audio_weight) * response["catalog_match"]["similarity"]}
                elif response["query_type"] == "semantic" and response["pipeline"]["semantic"] and response["mode"] == "AUTO":
                    mix = theme_mix if i in theme_evidence else 1.
                    contributions = {"semantic_theme": (1 - audio_weight) * mix * float((cosine[i] + 1) / 2)}
                    if i in theme_evidence:
                        evidence = theme_evidence[i]
                        contributions["lyric_passage"] = (1 - audio_weight) * (1 - mix) * (evidence.get("ranking_cosine", evidence["cosine"]) + 1) / 2
                elif response["text_query"] and available:
                    contributions = {name: (1 - audio_weight) * float(weight * feature[i])
                                     for name, weight, feature in zip(FEATURE_NAMES, weights, features)}
                contributions["audio"] = audio_weight * float(audio[i])
                contributions["lyric_bonus"] = float(bonuses.get(i, 0))
        failures = []
        for field, operator, bound in response["constraints"]:
            value = doc.get(field)
            passed = value is not None and math.isfinite(value) and {">": lambda: value > bound, "<": lambda: value < bound,
                ">=": lambda: value >= bound, "<=": lambda: value <= bound,
                "=": lambda: value == bound, "!=": lambda: value != bound}[operator]()
            if not passed:
                failures.append({"feature": field, "operator": operator, "bound": bound, "value": value})
        match = lyric_matches.get(i)
        rows.append({"track_id": track_id, "title": doc["track_name"], "artist": doc["track_artist"],
                     "sources": {name: ranks[i] for name, ranks in source_ranks.items() if i in ranks},
                     "rank_before_reranking": before_ranks.get(i), "final_rank": rank,
                     "displayed": track_id in displayed or track_id in related,
                     "displayed_group": "direct" if track_id in displayed else "related" if track_id in related else None,
                     "disposition": disposition, "failed_constraints": failures,
                     "raw_scores": {"bm25": float(bm[i]), "cosine": float(cosine[i]) if response["pipeline"]["semantic"] else None,
                                    "audio": float(audio[i]), "rrf": float(fusion[i])},
                     "features": values, "contributions": contributions,
                     "ordering_values": {"score": float(final[i]) if rank is not None else None,
                                         "popularity": doc.get("track_popularity"), "rrf": float(fusion[i]), "track_id": track_id},
                     "theme_evidence": theme_evidence.get(i),
                     "score": float(final[i]) if rank is not None else None,
                     "lyric_match": {"kind": match.kind, "similarity": match.similarity} if match else None})
    target = None
    if inspect_track_id:
        target = next((row for row in rows if row["track_id"] == inspect_track_id),
                      {"track_id": inspect_track_id, "disposition": "not_in_corpus"})
    return {"version": 2, "ranking": response["ranking"], "query_plan": {"planned_type": planned_kind, "effective_type": response["query_type"],
            "text_query": response["text_query"], "semantic_query": response["semantic_query"], "mood": response.get("mood"), "catalog_match": response.get("catalog_match"), "theme_profile": response.get("theme_profile")},
            "stages": {"corpus": len(engine.docs), "sources": {name: len(ranking) for name, ranking in rankings.items()},
                       "retrieved_unique": len(retrieved),
                       "eligible_after_filters": int(sum(mask & metadata_mask)) if response["mode"] == "AUTO" else None,
                       "audio_filter_stage": "before_retrieval" if response["mode"] == "AUTO" else "after_fusion",
                       "audio_filtered": sum(not value for value in mask) if response["mode"] == "AUTO" and response["pipeline"]["audio"] else sum(not mask[i] for i in retrieved) if response["pipeline"]["audio"] else 0,
                       "intent_filtered": int(sum(not value for value in metadata_mask)), "lyric_passages": passage_stats,
                       "selected_candidates": len(before), "displayed": len(displayed | related)},
            "timings_ms": timings, "audio_weight": audio_weight,
            "text_weights": dict(zip(FEATURE_NAMES, [float(w) for w in weights])),
            "manifest": {"corpus_sha256": corpus_hash(engine.docs), "implementation_sha256": implementation_hash(),
                         "config": json.loads(json.dumps(engine.config)), "model_name": engine.config["model_name"],
                         "model_revision": engine.semantic.config["model_revision"] if hasattr(engine.semantic, "config") else engine.config["model_revision"]},
            "candidates": rows, "target": target,
            "score_note": response["ranking"]["score_meaning"] + " Kontribusi dijumlahkan menjadi skor numerik. RRF mencatat pengambilan kandidat; urutan akhir mengikuti aturan order_by."}
