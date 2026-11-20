import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from music_ir.data import load_docs
from music_ir.engine import SearchEngine, load_config
from music_ir.metadata import MetadataIndex
from music_ir.passages import chunks, score_passages


class Missing:
    ready = False


class IntentTests(unittest.TestCase):
    def setUp(self):
        self.docs = [
            {"track_id": "a", "track_name": "A Love Song", "track_artist": "Alice, Bob", "lyrics": "when i see your face", "lyrics_available": True, "playlist_genre": ["pop"], "energy": .2},
            {"track_id": "b", "track_name": "Locked out of Heaven", "track_artist": "Bob", "lyrics": "a different lyric", "lyrics_available": True, "playlist_genre": ["rock"], "energy": .8},
            {"track_id": "c", "track_name": "Rock Your Body", "track_artist": "Bobby", "lyrics": "when i see the sky", "lyrics_available": True, "playlist_genre": ["pop"], "energy": .9},
        ]
        self.engine = SearchEngine(self.docs, load_config(), semantic=Missing())

    def test_artist_matches_whole_credit_not_partial_name(self):
        result = self.engine.search("Bob", top_k=30, trace=True, inspect_track_id="c")
        self.assertEqual({r["track_id"] for r in result["results"]}, {"a", "b"})
        self.assertEqual(result["query_type"], "artist")
        self.assertFalse(result["pipeline"]["degraded"])
        self.assertEqual(result["related_results"], [])
        self.assertEqual(result["trace"]["decisions"]["target"]["disposition"], "intent_filtered")

    def test_approximate_title_is_not_a_global_lyric_rewrite(self):
        result = self.engine.search("locked out in heaven", trace=True)
        self.assertEqual([r["track_id"] for r in result["results"]], ["b"])
        self.assertEqual(result["query_type"], "title")
        self.assertEqual(result["catalog_match"]["method"], "approximate")
        literal = self.engine.search('lirik "locked out in heaven"')
        self.assertEqual(literal["query_type"], "lyrics")
        self.assertIsNone(literal["catalog_match"])

    def test_genre_uses_playlist_label_and_audio_constraints(self):
        for query in ["rock song", "lagu rock", "musik bergenre rock", "genre rock"]:
            result = self.engine.search(query, trace=True)
            self.assertEqual([r["track_id"] for r in result["results"]], ["b"])
            self.assertEqual(result["query_type"], "genre")
            self.assertEqual(result["catalog_match"]["source"], "playlist_genre")
        self.assertEqual(self.engine.search("rock song dengan energy < 0.5")["results"], [])

    def test_exact_title_keeps_title_type_even_when_also_a_lyric(self):
        self.docs[0]["track_name"] = "When I See Your Face"
        engine = SearchEngine(self.docs, load_config(), semantic=Missing())
        result = engine.search("when i see your face")
        self.assertEqual(result["query_type"], "title")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["lyric_match"]["kind"], "exact")

    def test_lyric_results_separate_verified_hits_from_similar_songs(self):
        result = self.engine.search("when i see your face", top_k=3, trace=True)
        self.assertEqual([r["track_id"] for r in result["results"]], ["a"])
        self.assertTrue(result["related_results"])
        self.assertLessEqual(len(result["results"]) + len(result["related_results"]), 3)
        for row in result["trace"]["decisions"]["candidates"]:
            if row["displayed_group"] == "related":
                self.assertTrue(row["displayed"])
                self.assertIsNone(row["lyric_match"])

    def test_real_corpus_metadata_regressions(self):
        engine = SearchEngine(load_docs(), load_config(), semantic=Missing())
        artist = engine.search("bruno mars", top_k=100)
        self.assertEqual(len(artist["results"]), 9)
        self.assertTrue(all("Bruno Mars" in r["artist"].split(", ") for r in artist["results"]))
        self.assertEqual(engine.search("locked out in heaven")["results"][0]["title"], "Locked out of Heaven")
        self.assertEqual(engine.search("not like us")["query_type"], "title")
        self.assertTrue(all("rock" in r["genres"] for r in engine.search("rock song", top_k=30)["results"]))
        self.assertEqual(engine.search("when i see your face")["results"][0]["title"], "Just the Way You Are")

    def test_unknown_explicit_artist_and_genre_return_no_unrelated_filler(self):
        for query in ["artis Unknown Name", "genre Unknown Genre"]:
            result = self.engine.search(query)
            self.assertEqual(result["results"], [])
            self.assertFalse(result["pipeline"]["degraded"])

    def test_comma_inside_artist_name_is_matched_in_collaborations(self):
        self.docs[0]["track_artist"] = "Tyler, The Creator"
        self.docs[1]["track_artist"] = "Tyler, The Creator, Kali Uchis"
        engine = SearchEngine(self.docs, load_config(), semantic=Missing())
        self.assertEqual({r["track_id"] for r in engine.search("Tyler, The Creator")["results"]}, {"a", "b"})

    def test_exact_lyric_evidence_wins_over_an_approximate_title_guess(self):
        self.docs[0]["track_name"] = "One Day With You"
        self.docs[1]["lyrics"] = "One night with you"
        engine = SearchEngine(self.docs, load_config(), semantic=Missing())
        result = engine.search("one night with you")
        self.assertEqual(result["query_type"], "lyrics")
        self.assertEqual(result["results"][0]["track_id"], "b")

    def test_fuzzy_title_does_not_accept_multiple_changed_words(self):
        self.docs[0]["track_name"] = "A Long Night Alone With You"
        index = MetadataIndex(self.docs)
        self.assertIsNone(index.match("a long day alone beside you"))

    def test_breakup_facet_separates_generic_romance_into_related_results(self):
        class Semantic:
            ready = True
            def warmup(self): pass
            def scores(self, query): return np.array([.99, .8, .7])
            def passage_scores(self, query, candidates, **kwargs):
                return {i: {"cosine": .8, "text": "lyric evidence", "topic_cues": ["goodbye"] if i == 1 else []} for i in candidates}, {}
        result = SearchEngine(self.docs, load_config(), semantic=Semantic()).search("lagu tentang sulit melupakan seseorang")
        self.assertEqual([r["track_id"] for r in result["results"]], ["b"])
        self.assertEqual({r["track_id"] for r in result["related_results"]}, {"a", "c"})
        self.assertEqual(result["result_policy"]["primary"], "supported")

    def test_passage_signal_changes_theme_order_and_is_fully_explained(self):
        class Semantic:
            ready = True
            def warmup(self): pass
            def scores(self, query): return np.array([.9, .8, .7], dtype=np.float32)
            def passage_scores(self, query, candidates, **kwargs):
                return {i: {"cosine": [.1, .95, .2][i], "text": "lyric evidence", "method": "fixture"} for i in candidates}, {"passages": 3, "encoded": 3, "cache_hits": 0}
        engine = SearchEngine(self.docs, load_config(), semantic=Semantic())
        result = engine.search("lagu bermakna cinta", trace=True)
        self.assertEqual(result["results"][0]["track_id"], "b")
        self.assertTrue(result["pipeline"]["passage_reranking"])
        self.assertEqual(result["results"][0]["snippet_type"], "semantic")
        for row in result["trace"]["decisions"]["candidates"]:
            self.assertAlmostEqual(sum(row["contributions"].values()), row["score"], places=12)
            self.assertIn("lyric_passage", row["contributions"])

    def test_passage_failure_is_explicit_without_breaking_retrieval(self):
        class Semantic:
            ready = True
            def warmup(self): pass
            def scores(self, query): return np.array([.9, .8, .7])
            def passage_scores(self, *args, **kwargs): raise OSError("cache unavailable")
        result = SearchEngine(self.docs, load_config(), semantic=Semantic()).search("lagu bermakna cinta")
        self.assertTrue(result["pipeline"]["degraded"])
        self.assertTrue(result["warnings"])
        self.assertTrue(result["results"])


class PassageTests(unittest.TestCase):
    def test_chunks_preserve_source_and_cover_the_end(self):
        text = " ".join(f"word{i}" for i in range(400))
        parts = chunks(text)
        self.assertTrue(all(part in text for part in parts))
        self.assertTrue(parts[-1].endswith("word399"))
        self.assertEqual(chunks(""), [])

    def test_cache_reuses_content_and_invalidates_model_and_lyric_changes(self):
        class Model:
            def __init__(self): self.encoded = []
            def get_sentence_embedding_dimension(self): return 2
            def encode(self, texts, **kwargs):
                self.encoded.extend(texts)
                return np.tile([1., 0.], (len(texts), 1))
        model = Model()
        docs = [{"lyrics": "the same lyric passage"}]
        config = {"model_name": "fixture", "model_revision": "v1"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "passages.sqlite3"
            _, first = score_passages(model, config, docs, [0], "theme", path)
            _, cached = score_passages(model, config, docs, [0], "new theme", path)
            self.assertEqual(first["encoded"], 1)
            self.assertEqual(cached["encoded"], 0)
            self.assertEqual(cached["cache_hits"], 1)
            config["model_revision"] = "v2"
            self.assertEqual(score_passages(model, config, docs, [0], "theme", path)[1]["encoded"], 1)
            docs[0]["lyrics"] = "changed lyrics"
            self.assertEqual(score_passages(model, config, docs, [0], "theme", path)[1]["encoded"], 1)
