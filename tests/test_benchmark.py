import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from music_ir.api import app
from music_ir.benchmark import BenchmarkStore, draft_queries
from music_ir.data import load_docs
from music_ir.evaluate import evaluate, read_benchmark
from test_diagnostics import fixture_engine


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = fixture_engine()
        self.queries = [{"query_id": "dev-1", "query": "Stay", "category": "title", "split": "dev",
                         "group_id": "stay", "review_status": "draft", "intent_note": "Cari judul", "hint_track_ids": ["a"]},
                        {"query_id": "test-1", "query": "Other", "category": "title", "split": "test",
                         "group_id": "other", "review_status": "draft", "intent_note": "Cari judul", "hint_track_ids": ["c"]}]
        self.path = self.root / "queries.jsonl"
        self.write_queries()
        self.store = BenchmarkStore(self.engine.docs, self.path, self.root / "reviews")

    def write_queries(self):
        self.path.write_text("\n".join(json.dumps(q) for q in self.queries) + "\n", encoding="utf-8")

    def prepare(self):
        self.store.prepare_pool(self.engine, "dev-1", ["E1", "E2", "AUTO"], 10)

    def complete(self, approve=True):
        self.prepare()
        if approve:
            self.store.review("dev-1", "reviewer-1")
        for row in self.store.candidates("dev-1")["candidates"]:
            self.store.judge("dev-1", row["track_id"], "reviewer-1", 3 if row["track_id"] == "a" else 0)

    def test_draft_has_160_queries_and_does_not_generate_human_labels(self):
        rows = draft_queries(load_docs())
        self.assertEqual(len(rows), 160)
        counts = Counter((q["category"], q["split"]) for q in rows)
        for category in ["title", "artist", "lyrics", "semantic", "audio"]:
            self.assertEqual(counts[(category, "dev")], 8)
            self.assertEqual(counts[(category, "test")], 24)
        groups = {}
        for row in rows:
            self.assertEqual(row["review_status"], "draft")
            self.assertNotIn("relevance", row)
            self.assertEqual(groups.setdefault(row["group_id"], row["split"]), row["split"])

    def test_pool_is_blind_stable_and_starts_unjudged(self):
        self.prepare()
        first = self.store.candidates("dev-1", "reviewer-1")
        second = self.store.candidates("dev-1", "reviewer-1")
        self.assertEqual(first, second)
        self.assertTrue(first["prepared"])
        self.assertTrue(all(row["judgment"] is None for row in first["candidates"]))
        self.assertTrue(all("score" not in row and "sources" not in row for row in first["candidates"]))
        self.assertEqual(self.store.summary()["judgments"], 0)

    def test_human_reviews_persist_and_export_works_before_test_is_judged(self):
        self.complete()
        reopened = BenchmarkStore(self.engine.docs, self.path, self.root / "reviews")
        self.assertEqual(reopened.summary()["approved"], 1)
        bundle = reopened.export("dev", ["dev-1"])
        self.assertIn("dev-1,a,3,reviewer-1", bundle["qrels_csv"])
        query_path, labels_path = self.root / "export.jsonl", self.root / "qrels.csv"
        query_path.write_text(bundle["queries_jsonl"], encoding="utf-8")
        labels_path.write_text(bundle["qrels_csv"], encoding="utf-8")
        result = evaluate(self.engine, query_path, labels_path, self.root / "evaluation", ["E2", "AUTO"], "dev", 1)
        self.assertEqual(result["E2"]["all"]["ndcg@10"], 1.)
        self.assertEqual(result["E2"]["all"]["judged@10"], 1.)
        # The original file still includes an unreviewed/unjudged test query.
        self.queries[0]["review_status"] = "approved"
        self.write_queries()
        _, labels = read_benchmark(self.path, labels_path, self.engine.docs, required_split="dev")
        self.assertEqual(labels["dev-1"]["a"], 3)

    def test_export_rejects_unreviewed_incomplete_and_conflicting_judgments(self):
        self.complete(approve=False)
        with self.assertRaisesRegex(ValueError, "setujui"):
            self.store.export("dev")
        self.store.review("dev-1", "reviewer-1")
        self.store.judge("dev-1", "a", "reviewer-2", 0)
        with self.assertRaisesRegex(ValueError, "perbedaan"):
            self.store.export("dev")
        self.store.judge("dev-1", "a", "reviewer-2", 3)
        self.assertIn("reviewer-2", self.store.export("dev")["qrels_csv"])

    def test_no_implicit_grade_and_pool_must_be_complete(self):
        self.prepare()
        self.store.review("dev-1", "reviewer-1")
        self.store.judge("dev-1", "a", "reviewer-1", 3)
        with self.assertRaisesRegex(ValueError, "belum selesai"):
            self.store.export("dev")
        for grade in [True, 4, -1, "3"]:
            with self.assertRaises(ValueError):
                self.store.judge("dev-1", "a", "reviewer-1", grade)
        with self.assertRaises(ValueError):
            self.store.judge("dev-1", "missing", "reviewer-1", 3)

    def test_changed_query_or_corpus_does_not_reuse_old_reviews(self):
        self.complete()
        self.queries[0]["query"] = "A new meaning"
        self.write_queries()
        self.assertEqual(self.store.summary()["judgments"], 0)
        self.assertEqual(self.store.summary()["approved"], 0)
        self.assertFalse(self.store.candidates("dev-1")["prepared"])
        changed = [dict(doc) for doc in self.engine.docs]
        changed[0]["lyrics"] = "changed corpus"
        other = BenchmarkStore(changed, self.path, self.root / "reviews")
        self.assertEqual(other.summary()["judgments"], 0)
        with self.assertRaisesRegex(ValueError, "Corpus"):
            other.prepare_pool(self.engine, "dev-1", ["E2"])

    def test_group_leak_and_zero_relevant_query_are_rejected(self):
        self.queries[1]["group_id"] = "stay"
        self.write_queries()
        with self.assertRaisesRegex(ValueError, "group_id"):
            self.store.queries()
        self.queries[1]["group_id"] = "other"
        self.write_queries()
        self.complete()
        self.store.judge("dev-1", "a", "reviewer-1", 0)
        with self.assertRaisesRegex(ValueError, "Belum ada label"):
            self.store.export("dev")

    def test_benchmark_api_collects_only_explicit_human_grades(self):
        self.engine.benchmark_store = self.store
        with patch("music_ir.api.SearchEngine", return_value=self.engine), TestClient(app) as client:
            self.assertEqual(client.get("/benchmark").json()["judgments"], 0)
            self.assertEqual(client.post("/benchmark/queries/dev-1/pool", json={"modes": ["E2"], "depth": 2}).status_code, 200)
            self.assertEqual(client.put("/benchmark/queries/dev-1/review", json={"annotator": "human"}).status_code, 200)
            self.assertEqual(client.put("/benchmark/queries/dev-1/judgments", json={"annotator": "human", "track_id": "a", "grade": 3}).status_code, 200)
            self.assertEqual(client.get("/benchmark").json()["judgments"], 1)
            self.assertEqual(client.put("/benchmark/queries/dev-1/judgments", json={"annotator": "human", "track_id": "a", "grade": True}).status_code, 422)
            self.assertEqual(client.get("/benchmark/queries/missing").status_code, 404)
            self.assertEqual(client.get("/benchmark/export?split=dev").status_code, 422)
            self.assertTrue(all(row["judgment"] is None for row in client.get("/benchmark/queries/dev-1?annotator=another").json()["candidates"]))

    def test_draft_file_cannot_be_evaluated_and_degraded_auto_is_not_a_full_run(self):
        labels = self.root / "qrels.csv"
        labels.write_text("query_id,track_id,relevance,annotator\ndev-1,a,3,human\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "draft query"):
            evaluate(self.engine, self.path, labels, self.root / "out", ["E2"], "dev", 1)
        self.queries[0]["review_status"] = "approved"
        self.write_queries()
        original = self.engine.semantic.scores
        self.queries[0]["query"] = "a memory of leaving"
        self.write_queries()
        self.engine.semantic.scores = lambda query: (_ for _ in ()).throw(RuntimeError("fixture failure"))
        with self.assertRaisesRegex(RuntimeError, "fallback"):
            evaluate(self.engine, self.path, labels, self.root / "out", ["AUTO"], "dev", 1)
        self.engine.semantic.scores = original
