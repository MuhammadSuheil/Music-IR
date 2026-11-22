"""Opt-in read-only integration checks against the prepared Elasticsearch index."""
import os
import unittest

from music_ir.data import load_docs
from music_ir.engine import SearchEngine, load_config
from music_ir.lexical import INDEX


@unittest.skipUnless(os.environ.get("MUSIC_IR_TEST_ES") == "1", "Set MUSIC_IR_TEST_ES=1 setelah indeks Elasticsearch dibuat")
class ElasticsearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = SearchEngine(backend="elasticsearch")

    def test_index_has_entire_corpus(self):
        result = self.engine.lexical.request("GET", "/" + INDEX + "/_count")
        self.assertEqual(result["count"], 1437)

    def test_title_and_case(self):
        for mode in ["E1", "E2"]:
            response = self.engine.search("ＤＩＥ With A Smile", mode)
            self.assertEqual(response["results"][0]["track_id"], "2plbrEY59IikOBgBGLjaoe")

    def test_artist_collaboration(self):
        response = self.engine.search("Bruno Mars", "E2", 3)
        self.assertTrue(all("Bruno Mars" in song["artist"] for song in response["results"]))

    def test_lyrics_fragment(self):
        response = self.engine.search("I just woke up from a dream", "E2")
        self.assertIn("2plbrEY59IikOBgBGLjaoe", [song["track_id"] for song in response["results"]])

    def test_corpus_mismatch_is_rejected(self):
        docs = load_docs()
        docs[0]["track_name"] = "Different snapshot"
        engine = SearchEngine(docs, load_config(), backend="elasticsearch")
        with self.assertRaisesRegex(RuntimeError, "berbeda"):
            engine.search("Stay", "E2")
