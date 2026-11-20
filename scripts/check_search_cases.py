"""Replay the seven user cases plus lyric/mood guards against a local API.

Functional regression checks only: this does not generate relevance labels or
claim benchmark accuracy. Original exported traces are read without modification.
"""
import argparse
import json
import math
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CASES = ["bruno mars", "locked out in heaven", "lagu bermakna cinta", "rock song",
         "lagu tentang sulit melupakan seseorang", "not like us", "when i see your face",
         "lagu bermakna sedih", 'lirik "make the stars look like there not shining"']


def verify(number, data):
    results = data["results"]
    related = data.get("related_results", [])
    assert len(results) + len(related) <= 30
    assert not data["pipeline"]["degraded"], data["warnings"]
    assert len({r["track_id"] for r in results + related}) == len(results + related)
    for row in data["trace"]["decisions"]["candidates"]:
        if row["final_rank"]:
            assert math.isclose(sum(row["contributions"].values()), row["score"], abs_tol=1e-8)
    if number == 1:
        assert data["query_type"] == "artist" and len(results) == 9
        assert all("Bruno Mars" in r["artist"].split(", ") for r in results)
    elif number == 2:
        assert data["query_type"] == "title" and len(results) == 1
        assert results[0]["title"] == "Locked out of Heaven"
    elif number == 3:
        assert data["theme_profile"] == "romance" and data["pipeline"]["passage_reranking"]
        assert all(r.get("theme_evidence") for r in results)
    elif number == 4:
        assert data["query_type"] == "genre" and results
        assert all("rock" in r["genres"] for r in results)
    elif number == 5:
        assert data["theme_profile"] == "moving_on" and data["pipeline"]["passage_reranking"]
        assert results and all(r["theme_evidence"].get("topic_cues") for r in results)
    elif number == 6:
        assert data["query_type"] == "title" and len(results) == 1
        assert results[0]["title"] == "Not Like Us"
    elif number == 7:
        assert data["query_type"] == "lyrics" and results[0]["title"] == "Just the Way You Are"
        assert all(r["lyric_match"] for r in results)
        assert all(not r["lyric_match"] for r in related)
    elif number == 8:
        assert data["mood"]["basis"] == "both" and results
        assert all(r["audio"]["valence"] <= .5 and r["audio"]["energy"] <= .65 for r in results + related)
    elif number == 9:
        assert results[0]["title"] == "Just the Way You Are"
        assert results[0]["lyric_match"]["kind"] == "approximate"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--baseline-dir", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "regressions" / "search-cases")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    summary = []
    for number, query in enumerate(CASES, 1):
        started = time.perf_counter()
        request = urllib.request.Request(args.base_url.rstrip("/") + "/search", data=json.dumps({"query": query, "top_k": 30, "trace": True}).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=300) as stream:
            data = json.load(stream)
        (args.output / f"case-{number}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        verify(number, data)
        row = {"case": number, "query": query, "checks_passed": True, "query_type": data["query_type"],
               "primary_count": len(data["results"]), "related_count": len(data["related_results"]),
               "top5": [{"title": r["title"], "artist": r["artist"]} for r in data["results"][:5]],
               "http_wall_seconds": round(time.perf_counter() - started, 3),
               "passages": data["trace"]["decisions"]["stages"].get("lyric_passages")}
        if args.baseline_dir and number <= 7:
            name = "search-trace.json" if number == 1 else f"search-trace {number}.json"
            before = json.loads((args.baseline_dir / name).read_text(encoding="utf-8-sig"))
            assert before["query"] == query
            row["before"] = {"query_type": before["query_type"], "count": len(before["results"]),
                             "top5": [{"title": r["title"], "artist": r["artist"]} for r in before["results"][:5]]}
        summary.append(row)
        print(json.dumps(row, ensure_ascii=True), flush=True)
    (args.output / "summary.json").write_text(json.dumps({"scope": "functional checks, not a relevance benchmark", "cases": summary}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
