import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from music_ir.api import app
from music_ir.audio import parse
from music_ir.data import load_docs
from music_ir.engine import SearchEngine, load_config
from music_ir.query import plan_query


class Semantic:
    ready = True

    def warmup(self):
        pass

    def scores(self, query):
        return np.array([.99, .98, .97, .7])


def engine():
    docs = []
    for track_id, title, valence, energy in [
        ("cheerful", "A Sweet Love Song", .88, .79),
        ("intense", "Loud Heartbreak", .2, .95),
        ("missing", "Unknown Audio", None, None),
        ("sad", "Quiet Farewell", .2, .4),
    ]:
        docs.append({"track_id": track_id, "track_name": title, "track_artist": "Test Artist",
                     "lyrics": "a story about longing and feeling broken", "lyrics_available": True,
                     "valence": valence, "energy": energy, "tempo": 100})
    return SearchEngine(docs, load_config(), semantic=Semantic())


class MoodTests(unittest.TestCase):
    def test_sad_query_variants_share_meaning_and_mood(self):
        for query in ["lagu bermakna sedih", "lagu yang bermakna sedih", "lagu dengan makna sedih",
                      "lagu bertema sedih", "lagu tentang kesedihan", "lagu sedih"]:
            with self.subTest(query=query):
                plan = plan_query(query)
                self.assertEqual(plan.kind, "semantic")
                self.assertEqual(plan.mood, "sad")
                self.assertIn("sadness", plan.semantic_text)
        intent = parse("lagu bermakna sedih dengan tempo > 90 BPM")
        self.assertEqual(plan_query(intent.text, "lagu bermakna sedih dengan tempo > 90 BPM").mood, "sad")

    def test_both_filters_cheerful_intense_and_missing_audio(self):
        result = engine().search("lagu bermakna sedih", trace=True, inspect_track_id="cheerful")
        self.assertEqual([r["track_id"] for r in result["results"]], ["sad"])
        self.assertEqual(result["mood"]["basis"], "both")
        self.assertTrue(result["pipeline"]["semantic"])
        self.assertTrue(result["pipeline"]["audio"])
        target = result["trace"]["decisions"]["target"]
        self.assertEqual(target["disposition"], "audio_filtered")
        self.assertEqual({c["feature"] for c in target["failed_constraints"]}, {"energy", "valence"})
        for row in result["trace"]["decisions"]["candidates"]:
            if row["final_rank"]:
                self.assertAlmostEqual(sum(row["contributions"].values()), row["score"])

    def test_lyrics_only_does_not_assume_audio_is_sad(self):
        result = engine().search("lagu bermakna sedih", mood_basis="lyrics")
        self.assertEqual(result["results"][0]["track_id"], "cheerful")
        self.assertEqual(result["constraints"], [])
        self.assertFalse(result["pipeline"]["audio"])

    def test_audio_only_needs_no_encoder(self):
        search = engine()
        search.semantic = type("Unavailable", (), {"ready": False})()
        result = search.search("lagu bermakna sedih", mood_basis="audio")
        self.assertEqual(result["results"][0]["track_id"], "sad")
        self.assertFalse(result["pipeline"]["semantic"])
        self.assertFalse(result["pipeline"]["degraded"])
        self.assertEqual(result["query_type"], "audio")

    def test_audio_filter_is_applied_before_candidate_budget(self):
        search = engine()
        search.config["candidate_limit"] = 1
        self.assertEqual(search.search("lagu sedih")["candidate_ids"], ["sad"])

    def test_explicit_constraints_are_not_relaxed(self):
        result = engine().search("lagu bermakna sedih dengan valence > 0.9")
        self.assertEqual(result["results"], [])
        self.assertIn(("valence", ">", .9), result["constraints"])
        self.assertIn(("valence", "<=", .5), result["constraints"])

    def test_titles_and_quoted_lyrics_are_not_mood_requests(self):
        self.assertIsNone(plan_query('lirik "sadness and sorrow in my heart"').mood)
        self.assertIsNone(plan_query("Sad", metadata_names={"sad"}).mood)
        self.assertIsNone(engine().search("A Sweet Love Song")["mood"])

    def test_experiments_unchanged_and_unsupported_scope_is_rejected(self):
        search = engine()
        self.assertIsNone(search.search("lagu sedih", "E5")["mood"])
        for query, mode, basis in [("lagu sedih", "E5", "both"), ("ordinary words", "AUTO", "both"),
                                   ("lagu sedih", "AUTO", "invalid")]:
            with self.assertRaises(ValueError):
                search.search(query, mode, mood_basis=basis)

    def test_api_validates_mood_basis(self):
        with patch("music_ir.api.SearchEngine", return_value=engine()), TestClient(app) as client:
            result = client.post("/search", json={"query": "lagu bermakna sedih", "mood_basis": "both"})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["results"][0]["track_id"], "sad")
            self.assertEqual(client.post("/search", json={"query": "lagu sedih", "mood_basis": "invalid"}).status_code, 422)

    def test_real_sugar_is_excluded_by_general_policy_without_a_blacklist(self):
        rows = load_docs()
        sugar = next(d for d in rows if d["track_name"] == "Sugar" and d["track_artist"] == "Maroon 5")
        other = next(d for d in rows if d["track_name"] == "THE LONELIEST")

        class TwoScores(Semantic):
            def scores(self, query):
                return np.array([.99, .7])

        search = SearchEngine([sugar, other], load_config(), semantic=TwoScores())
        result = search.search("lagu bermakna sedih")
        self.assertEqual(result["results"][0]["track_id"], other["track_id"])
        self.assertNotIn(sugar["track_id"], result["candidate_ids"])
        self.assertEqual(search.search("Sugar")["results"][0]["track_id"], sugar["track_id"])
