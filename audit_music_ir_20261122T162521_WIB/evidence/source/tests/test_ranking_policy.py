import unittest

from music_ir.data import load_docs
from music_ir.engine import SearchEngine, load_config


class Missing:
    ready = False


class RankingPolicyTests(unittest.TestCase):
    def engine(self):
        docs = []
        for track_id, popularity, tempo in [("a", 10, 125), ("b", 50, 200), ("z", 99, 140), ("excluded", 100, 120)]:
            docs.append({"track_id": track_id, "track_name": track_id, "track_artist": "Artist",
                         "lyrics": "", "lyrics_available": False, "tempo": tempo, "track_popularity": popularity,
                         "playlist_genre": ["rock"]})
        return SearchEngine(docs, load_config(), semantic=Missing())

    def test_hard_constraint_scores_are_eligibility_and_order_by_popularity(self):
        result = self.engine().search("tempo > 120 BPM", trace=True)
        self.assertEqual([r["track_id"] for r in result["results"]], ["z", "b", "a"])
        self.assertTrue(all(r["score"] == 1 for r in result["results"]))
        self.assertEqual(result["ranking"]["score_kind"], "eligibility")
        self.assertIn("popularity_desc", result["ranking"]["order_by"])
        decisions = result["trace"]["decisions"]
        self.assertEqual(decisions["stages"]["eligible_after_filters"], 3)
        self.assertEqual(decisions["ranking"], result["ranking"])
        self.assertEqual(decisions["candidates"][0]["ordering_values"]["popularity"], 99)

    def test_popularity_selection_happens_before_candidate_budget(self):
        engine = self.engine()
        engine.config["candidate_limit"] = 1
        self.assertEqual(engine.search("tempo > 120 BPM")["candidate_ids"], ["z"])

    def test_filter_does_not_implicitly_prefer_higher_tempo(self):
        result = self.engine().search("tempo > 120 BPM")
        self.assertEqual(result["results"][0]["audio"]["tempo"], 140)
        preferred = self.engine().search("tempo > 120 BPM dan tempo cepat")
        self.assertEqual(preferred["results"][0]["audio"]["tempo"], 200)
        self.assertEqual(preferred["ranking"]["score_kind"], "audio_preference")
        self.assertGreater(len({r["score"] for r in preferred["results"]}), 1)

    def test_experimental_e5_keeps_its_previous_id_tie_break(self):
        result = self.engine().search("tempo > 120 BPM", "E5")
        self.assertEqual([r["track_id"] for r in result["results"]], ["a", "b", "z"])
        self.assertNotIn("popularity_desc", result["ranking"]["order_by"])

    def test_exact_genre_match_has_constant_indicator_with_explicit_order(self):
        result = self.engine().search("rock song")
        self.assertEqual(result["ranking"]["score_kind"], "eligibility")
        self.assertTrue(all(r["score"] == 1 for r in result["results"]))
        self.assertEqual([r["track_id"] for r in result["results"]], ["excluded", "z", "b", "a"])

    def test_latest_real_cases_keep_all_constraints_and_trace_sums(self):
        engine = SearchEngine(load_docs(), load_config(), semantic=Missing())
        for query in ["tempo > 120 BPM", "rock song"]:
            result = engine.search(query, top_k=30, trace=True)
            self.assertEqual(result["ranking"]["score_kind"], "eligibility")
            popularity = [r["popularity"] or 0 for r in result["results"]]
            self.assertEqual(popularity, sorted(popularity, reverse=True))
            for row in result["trace"]["decisions"]["candidates"]:
                if row["final_rank"]:
                    self.assertEqual(sum(row["contributions"].values()), row["score"])
            if query.startswith("tempo"):
                self.assertEqual(result["trace"]["decisions"]["stages"]["eligible_after_filters"], 730)
                self.assertTrue(all(r["audio"]["tempo"] > 120 for r in result["results"]))
                self.assertEqual(result["results"][0]["title"], "Die With A Smile")
            else:
                self.assertEqual(result["trace"]["decisions"]["stages"]["eligible_after_filters"], 212)
                self.assertTrue(all("rock" in r["genres"] for r in result["results"]))
