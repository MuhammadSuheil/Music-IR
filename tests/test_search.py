import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from music_ir.audio import audio_scores, parse
from music_ir.data import load_docs, prepare
from music_ir.engine import SearchEngine, load_config
from music_ir.evaluate import metrics


def song(track_id, title, artist, lyrics, tempo=120, energy=.5):
    return {"track_id": track_id, "track_name": title, "track_artist": artist, "lyrics": lyrics,
            "lyrics_available": bool(lyrics), "tempo": tempo, "energy": energy}


class FakeSemantic:
    """Deterministic fixture only; never used by the application."""
    ready = True
    def warmup(self):
        pass
    def scores(self, query):
        return np.array([.2, .9, .1])


class MissingSemantic:
    ready = False

    def warmup(self):
        raise RuntimeError("fixture: missing semantic model")

    def scores(self, query):
        raise AssertionError("Unavailable semantic model must not be queried")


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.docs = [song("a", "Stay", "Alice, Bob", "stay with me forever", 120, .2),
                     song("b", "Goodbye", "Carol", "the night has gone", 130, .9),
                     song("c", "Other", "Alice", "", None, None)]
        self.engine = SearchEngine(self.docs, load_config(), semantic=FakeSemantic())

    def test_default_pipeline_matches_e5_with_semantic(self):
        for query in ["a memory of leaving", "a memory of leaving dengan energi rendah", "tempo > 120 BPM"]:
            with self.subTest(query=query):
                automatic = self.engine.search(query)
                explicit = self.engine.search(query, "E5")
                self.assertEqual(automatic["mode"], "AUTO")
                self.assertEqual(automatic["results"], explicit["results"])
                self.assertEqual(automatic["candidate_ids"], explicit["candidate_ids"])
                self.assertEqual(automatic["warnings"], [])
                self.assertFalse(automatic["pipeline"]["degraded"])

    def test_default_pipeline_retrieves_meaning_without_word_matches(self):
        result = self.engine.search("a memory of leaving")
        self.assertTrue(result["pipeline"]["semantic"])
        self.assertEqual(result["results"][0]["track_id"], "b")

    def test_missing_semantic_falls_back_with_renormalized_weights(self):
        self.engine.semantic = MissingSemantic()
        result = self.engine.search("stay with", trace=True)
        self.assertFalse(result["pipeline"]["semantic"])
        self.assertTrue(result["pipeline"]["degraded"])
        self.assertTrue(result["warnings"])
        self.assertEqual(result["results"][0]["track_id"], "a")
        self.assertAlmostEqual(result["results"][0]["score"], 1 / 6)
        self.assertEqual(result["trace"]["features"][0][1], 0)
        self.assertFalse(any("Kemiripan makna" in reason for reason in result["results"][0]["reasons"]))
        # Meaning-only queries do not get synthetic semantic candidates.
        self.assertEqual(self.engine.search("unmatched words")["results"], [])

    def test_missing_semantic_keeps_audio_constraints_and_audio_only_path(self):
        self.engine.semantic = MissingSemantic()
        mixed = self.engine.search("Alice dengan tempo >= 120 BPM dan energi < 0,5")
        self.assertEqual([r["track_id"] for r in mixed["results"]], ["a"])
        self.assertTrue(mixed["pipeline"]["audio"])
        self.assertFalse(mixed["pipeline"]["degraded"])
        self.assertEqual(mixed["query_type"], "artist")
        self.assertEqual(self.engine.search("Alice dengan tempo > 999 BPM")["results"], [])
        pure = self.engine.search("tempo > 120 BPM")
        self.assertEqual([r["track_id"] for r in pure["results"]], ["b"])
        self.assertFalse(pure["pipeline"]["semantic"])
        self.assertFalse(pure["pipeline"]["degraded"])
        self.assertEqual(pure["warnings"], [])

    def test_semantic_failures_fallback_only_in_auto(self):
        class LoadingFailure(MissingSemantic):
            ready = True

        class EncodingFailure(FakeSemantic):
            def scores(self, query):
                raise OSError("fixture: inference failed")

        for semantic in [MissingSemantic(), LoadingFailure(), EncodingFailure()]:
            self.engine.semantic = semantic
            with self.subTest(semantic=type(semantic).__name__):
                result = self.engine.search("stay with")
                self.assertEqual(result["results"][0]["track_id"], "a")
                self.assertTrue(result["pipeline"]["degraded"])
                self.assertTrue(result["warnings"])
                for mode in ["E3", "E4", "E5"]:
                    with self.assertRaises((RuntimeError, OSError)):
                        self.engine.search("Stay", mode)

    def test_cosine_only_configuration_can_fallback(self):
        self.engine.semantic = MissingSemantic()
        self.engine.config["text_weights"] = [0., 1., 0., 0., 0.]
        result = self.engine.search("forever")
        expected = self.engine.search("forever", "E2")
        self.assertEqual([r["track_id"] for r in result["results"]],
                         [r["track_id"] for r in expected["results"]])
        self.assertTrue(all(np.isfinite(r["score"]) for r in result["results"]))

    def test_api_defaults_to_auto_and_reports_fallback(self):
        from fastapi.testclient import TestClient
        from music_ir.api import app
        self.engine.semantic = MissingSemantic()
        with patch("music_ir.api.SearchEngine", return_value=self.engine), TestClient(app) as client:
            self.assertEqual(client.get("/health").json()["default_mode"], "AUTO")
            schema = client.get("/openapi.json").json()["components"]["schemas"]["SearchRequest"]
            self.assertEqual(schema["properties"]["mode"]["default"], "AUTO")
            result = client.post("/search", json={"query": "stay with"})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["mode"], "AUTO")
            self.assertTrue(result.json()["pipeline"]["degraded"])
            self.assertTrue(result.json()["warnings"])
            explicit = client.post("/search", json={"query": "stay with", "mode": "AUTO"})
            self.assertEqual(explicit.status_code, 200)
            self.assertEqual(explicit.json()["mode"], "AUTO")
            self.assertEqual(client.post("/search", json={"query": "Stay", "mode": "E4"}).status_code, 503)
            self.assertEqual(client.post("/search", json={"query": "Stay", "mode": "invalid"}).status_code, 422)

    def test_api_startup_does_not_require_encoder_loading(self):
        from fastapi.testclient import TestClient
        from music_ir.api import app

        class LoadingFailure(MissingSemantic):
            ready = True

        self.engine.semantic = LoadingFailure()
        with patch("music_ir.api.SearchEngine", return_value=self.engine), TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            result = client.post("/search", json={"query": "stay with"})
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json()["pipeline"]["degraded"])

    def test_title_case_unicode_and_collaboration(self):
        self.assertEqual(self.engine.search("ＳＴＡＹ", "E2")["results"][0]["track_id"], "a")
        self.assertEqual(self.engine.search("Bob", "E2")["results"][0]["track_id"], "a")

    def test_no_lyrics_still_searchable(self):
        self.assertEqual(self.engine.search("Other", "E2")["results"][0]["track_id"], "c")

    def test_same_candidates_e3_e4(self):
        e3 = self.engine.search("Stay", "E3")
        e4 = self.engine.search("Stay", "E4")
        self.assertEqual(set(e3["candidate_ids"]), set(e4["candidate_ids"]))
        self.assertEqual(len(e3["candidate_ids"]), len(set(e3["candidate_ids"])))

    def test_e5_equals_e4_without_audio(self):
        self.assertEqual(self.engine.search("Stay", "E4")["results"], self.engine.search("Stay", "E5")["results"])

    def test_audio_boundary_and_missing(self):
        result = self.engine.search("tempo > 120 BPM", "E5")
        self.assertEqual([r["track_id"] for r in result["results"]], ["b"])
        self.assertEqual(self.engine.search("tempo > 999 BPM", "E5")["results"], [])
        result = self.engine.search("tempo >= 120 BPM dan energi < 0,5", "E5")
        self.assertEqual([r["track_id"] for r in result["results"]], ["a"])

    def test_soft_audio_prefers_high_energy(self):
        self.assertEqual(self.engine.search("energi tinggi", "E5")["results"][0]["track_id"], "b")

    def test_negation(self):
        result = self.engine.search("tempo tidak di atas 120 BPM", "E5")
        self.assertEqual([r["track_id"] for r in result["results"]], ["a"])

    def test_text_candidates_obey_audio_constraint(self):
        result = self.engine.search("Stay dengan tempo > 120 BPM", "E5")
        self.assertTrue(all(r["audio"]["tempo"] > 120 for r in result["results"]))

    def test_invalid_query(self):
        for text in ["   ", "!!!", "energi > 2", "tempo >= nope", "energi tinggi dan energi rendah"]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.engine.search(text, "E5")

    def test_audio_only_needs_no_semantic_model(self):
        class Missing:
            ready = False
            def warmup(self):
                raise RuntimeError("missing")
        engine = SearchEngine(self.docs, load_config(), semantic=Missing())
        self.assertTrue(engine.search("tempo > 120 BPM", "E5")["results"])
        with self.assertRaises(RuntimeError):
            engine.search("lagu sedih", "E4")

    def test_metrics_known_ranking(self):
        values = metrics(["a", "b"], {"a": 3, "b": 2, "c": 0})
        self.assertEqual(values, {"ndcg@10": 1., "mrr@10": 1., "recall@100": 1.})
        self.assertEqual(metrics([], {"a": 3})["mrr@10"], 0)

    def test_percentile_ties_and_constant_fields(self):
        docs = [song("a", "A", "A", "", 120, .1), song("b", "B", "B", "", 120, .1), song("c", "C", "C", "", 120, .9)]
        _, values = audio_scores(docs, parse("energi tinggi"))
        self.assertEqual(values[0], values[1])
        self.assertGreater(values[2], values[0])
        _, values = audio_scores(docs, parse("tempo cepat"))
        np.testing.assert_array_equal(values, [.5, .5, .5])

    def test_evaluation_runner_on_reviewed_fixture(self):
        import csv
        import json
        from music_ir.evaluate import evaluate
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            (directory / "queries.jsonl").write_text(json.dumps({"query_id": "q", "query": "Stay", "category": "title", "split": "test", "group_id": "stay"}), encoding="utf-8")
            (directory / "qrels.csv").write_text("query_id,track_id,relevance,annotator\nq,a,3,test\nq,b,0,test\nq,c,0,test\n", encoding="utf-8")
            result = evaluate(self.engine, directory / "queries.jsonl", directory / "qrels.csv", directory / "out", ["E1", "E2", "E3", "E4", "AUTO"], repeats=1)
            self.assertEqual(result["E1"]["all"]["ndcg@10"], 1)
            self.assertEqual(result["AUTO"]["all"]["ndcg@10"], 1)
            self.assertEqual(result["E3"]["all"]["recall@100"], result["E4"]["all"]["recall@100"])

    def test_test_and_dev_groups_must_not_overlap(self):
        import json
        from music_ir.evaluate import read_benchmark
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            queries = [{"query_id": "a", "query": "Stay", "category": "title", "split": "dev", "group_id": "same"},
                       {"query_id": "b", "query": "Stay", "category": "title", "split": "test", "group_id": "same"}]
            (directory / "q.jsonl").write_text("\n".join(json.dumps(q) for q in queries), encoding="utf-8")
            (directory / "r.csv").write_text("query_id,track_id,relevance,annotator\na,a,3,test\nb,a,3,test\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "group_id"):
                read_benchmark(directory / "q.jsonl", directory / "r.csv", self.docs)

    def test_tuning_uses_dev_and_keeps_main_config(self):
        import json
        from music_ir.tune import tune
        from music_ir.data import ROOT
        original = (ROOT / "config.json").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            queries = [{"query_id": "dev", "query": "Stay", "category": "title", "split": "dev", "group_id": "stay"},
                       {"query_id": "test", "query": "night", "category": "lyrics", "split": "test", "group_id": "night"}]
            (directory / "q.jsonl").write_text("\n".join(json.dumps(q) for q in queries), encoding="utf-8")
            (directory / "r.csv").write_text("query_id,track_id,relevance,annotator\ndev,a,3,test\ntest,b,3,test\n", encoding="utf-8")
            tune(self.engine, directory / "q.jsonl", directory / "r.csv", directory / "out")
            trials = json.loads((directory / "out" / "trials.json").read_text(encoding="utf-8"))
            self.assertEqual(trials["query_ids"], ["dev"])
            self.assertEqual(max(t["ndcg@10"] for t in trials["text_trials"]), 1)
            self.assertEqual(len(trials["text_trials"]), 70)
        self.assertEqual((ROOT / "config.json").read_text(encoding="utf-8"), original)

    def test_prepare_merge_without_discarding_versions(self):
        import csv
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.csv"
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["track_id", "track_name", "track_artist", "lyrics", "playlist_genre"])
                writer.writeheader()
                writer.writerows([{"track_id": "a", "track_name": "Same", "track_artist": "A", "lyrics": "", "playlist_genre": "pop"},
                                  {"track_id": "a", "track_name": "Same", "track_artist": "A", "lyrics": "words", "playlist_genre": "rock"},
                                  {"track_id": "b", "track_name": "Same", "track_artist": "A", "lyrics": "", "playlist_genre": "pop"}])
            audit = prepare(path, Path(directory) / "out")
            self.assertEqual(audit["unique_tracks"], 2)
            self.assertEqual(audit["tracks_without_lyrics"], 1)


class CorpusTests(unittest.TestCase):
    def test_supplied_dataset(self):
        docs = load_docs()
        self.assertEqual(len(docs), 1437)
        self.assertEqual(len({d["track_id"] for d in docs}), 1437)
        self.assertEqual(sum(not d["lyrics_available"] for d in docs), 33)

    def test_api_validation_and_semantic_unavailable(self):
        from fastapi.testclient import TestClient
        from music_ir.api import app
        with TestClient(app) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            response = client.post("/search", json={"query": "Die With A Smile", "mode": "E2"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["results"][0]["title"], "Die With A Smile")
            self.assertEqual(client.post("/search", json={"query": "   "}).status_code, 422)
            self.assertEqual(client.post("/search", json={"query": "test", "top_k": 101}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
