import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from music_ir.api import app
from music_ir.engine import SearchEngine, load_config


class Semantic:
    ready = True

    def warmup(self):
        pass

    def scores(self, query):
        return np.array([.2, .9, .1])


def fixture_engine():
    docs = [{"track_id": "a", "track_name": "Stay", "track_artist": "Alice", "lyrics": "stay with me forever",
             "lyrics_available": True, "tempo": 100, "energy": .2},
            {"track_id": "b", "track_name": "Goodbye", "track_artist": "Bob", "lyrics": "a different story",
             "lyrics_available": True, "tempo": 140, "energy": .9},
            {"track_id": "c", "track_name": "Other", "track_artist": "Carol", "lyrics": "",
             "lyrics_available": False, "tempo": None, "energy": None}]
    return SearchEngine(docs, load_config(), semantic=Semantic())


class DiagnosticsTests(unittest.TestCase):
    def test_trace_preserves_results_and_contributions_sum_to_scores(self):
        engine = fixture_engine()
        for mode in ["AUTO", "E1", "E2", "E3", "E4", "E5"]:
            for query in ["Stay", "lagu tentang kehilangan", 'lirik "stay with me forever"', "energi tinggi"]:
                with self.subTest(mode=mode, query=query):
                    normal = engine.search(query, mode)
                    traced = engine.search(query, mode, trace=True)
                    self.assertEqual(normal["results"], traced["results"])
                    self.assertEqual(normal["candidate_ids"], traced["candidate_ids"])
                    rows = traced["trace"]["decisions"]["candidates"]
                    for row in rows:
                        if row["final_rank"] is not None:
                            self.assertAlmostEqual(sum(row["contributions"].values()), row["score"])
                    self.assertIn("features", traced["trace"])
                    self.assertIn("model_loading", traced["trace"]["decisions"]["timings_ms"])

    def test_inspector_distinguishes_candidate_limit_and_missing_track(self):
        engine = fixture_engine()
        engine.config["candidate_limit"] = 1
        target = engine.search("stay with", trace=True, inspect_track_id="b")["trace"]["decisions"]["target"]
        self.assertEqual(target["disposition"], "candidate_limit")
        self.assertEqual(target["sources"]["semantic"], 1)
        missing = engine.search("Stay", trace=True, inspect_track_id="missing")["trace"]["decisions"]["target"]
        self.assertEqual(missing["disposition"], "not_in_corpus")

    def test_filtered_target_explains_failed_constraint(self):
        target = fixture_engine().search("Stay dengan tempo > 120 BPM", trace=True, inspect_track_id="a")["trace"]["decisions"]["target"]
        self.assertEqual(target["disposition"], "audio_filtered")
        self.assertEqual(target["failed_constraints"], [{"feature": "tempo", "operator": ">", "bound": 120., "value": 100}])
        self.assertIsNone(target["final_rank"])

    def test_api_only_returns_trace_when_requested(self):
        with patch("music_ir.api.SearchEngine", return_value=fixture_engine()), TestClient(app) as client:
            self.assertNotIn("trace", client.post("/search", json={"query": "Stay"}).json())
            result = client.post("/search", json={"query": "Stay", "inspect_track_id": "a"})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["trace"]["decisions"]["target"]["track_id"], "a")
            self.assertEqual(client.post("/search", json={"query": "Stay", "inspect_track_id": "x" * 101}).status_code, 422)
