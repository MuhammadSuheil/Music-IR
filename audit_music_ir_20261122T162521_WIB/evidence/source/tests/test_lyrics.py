import unittest

import numpy as np

from music_ir.engine import SearchEngine, load_config
from music_ir.lyrics import LyricIndex, lyric_tokens
from music_ir.query import plan_query
from music_ir.data import load_docs


def song(track_id, title, lyrics, tempo=120):
    return {"track_id": track_id, "track_name": title, "track_artist": "Test Artist",
            "lyrics": lyrics, "lyrics_available": bool(lyrics), "tempo": tempo}


class SemanticFixture:
    ready = True

    def __init__(self):
        self.queries = []

    def warmup(self):
        pass

    def scores(self, query):
        self.queries.append(query)
        return np.array([.9, .1, .6])


class LyricTests(unittest.TestCase):
    def setUp(self):
        # Semantic and metadata signals deliberately favor the distractor.
        self.docs = [song("wrong", "Not Like Us", "not like us " * 30),
                     song("right", "A Different Title", "An opening line\nMake the stars look like they're not shining\nA closing line", 100),
                     song("third", "Other", "a completely different story", 140)]
        self.semantic = SemanticFixture()
        self.engine = SearchEngine(self.docs, load_config(), semantic=self.semantic)

    def test_misremembered_words_return_the_track_with_matching_lyric(self):
        for query in ['make the stars look like there not shining', 'lirik "make the stars look like there not shining"']:
            with self.subTest(query=query):
                response = self.engine.search(query)
                self.assertEqual(response["results"][0]["track_id"], "right")
                self.assertEqual(response["query_type"], "lyrics")
                result = response["results"][0]
                self.assertEqual(result["lyric_match"]["kind"], "approximate")
                self.assertIn("they're", result["snippet"])
                self.assertTrue(any("toleransi" in reason for reason in result["reasons"]))

    def test_contractions_punctuation_and_line_breaks_are_normalized(self):
        self.assertEqual(lyric_tokens("THEY’RE, you're!"), ("they", "are", "you", "are"))
        index = LyricIndex([song("x", "Unknown", "You’re the one\nI have waited for.")])
        match = index.match("you are the one i have waited for")[0]
        self.assertEqual(match.kind, "exact")
        self.assertEqual(match.snippet, "You’re the one I have waited for")

    def test_transposed_character_typo_is_bounded(self):
        index = LyricIndex([song("x", "Unknown", "Lights will guide you home")])
        match = index.match("lights will guied you home")[0]
        self.assertEqual(match.kind, "approximate")
        self.assertGreater(match.similarity, .9)
        self.assertEqual(index.match("lights guide a totally different story"), {})

    def test_disconnected_words_do_not_count_as_a_lyric_phrase(self):
        index = LyricIndex([song("x", "Unknown", "stars " + "unrelated " * 15 + "make " + "unrelated " * 15 + "shining look like not the")])
        self.assertEqual(index.match("make the stars look like there not shining"), {})
        self.assertEqual(index.match("not like"), {})

    def test_evidenced_track_is_retained_with_a_tiny_candidate_budget(self):
        self.engine.config["candidate_limit"] = 1
        response = self.engine.search('lirik "make the stars look like there not shining"')
        self.assertEqual(response["candidate_ids"], ["right"])
        self.assertEqual(response["candidate_count"], 1)

    def test_lyric_priority_does_not_bypass_audio_constraints(self):
        response = self.engine.search('lirik "make the stars look like there not shining" dengan tempo > 120 BPM')
        self.assertNotIn("right", response["candidate_ids"])
        self.assertTrue(all(r["audio"]["tempo"] > 120 for r in response["results"]))

    def test_quoted_audio_words_are_literal(self):
        response = self.engine.search('lirik "energi tinggi dalam hati"')
        self.assertEqual(response["preferences"], {})
        self.assertEqual(response["text_query"], "energi tinggi dalam hati")
        self.assertFalse(response["pipeline"]["audio"])

    def test_no_evidence_is_reported_without_claiming_a_lyric_match(self):
        response = self.engine.search('lirik "unmatched complete quotation from elsewhere"')
        self.assertTrue(response["warnings"])
        self.assertTrue(all(r["lyric_match"] is None for r in response["results"]))
        for query in ['lirik ""', 'lirik "!!!"']:
            with self.assertRaises(ValueError):
                self.engine.search(query)

    def test_experiment_modes_keep_their_original_ranking(self):
        query = "make the stars look like there not shining"
        response = self.engine.search(query, "E5")
        self.assertEqual(response["results"][0]["track_id"], "wrong")
        self.assertTrue(all(r["lyric_match"] is None for r in response["results"]))


class QueryPlanTests(unittest.TestCase):
    def test_theme_wrappers_and_moods_are_focused_without_audio_inference(self):
        for query, focus in [("lagu tentang kehilangan", "kehilangan"),
                             ("a song about missing someone", "missing someone"),
                             ("lagu happy", "happy")]:
            plan = plan_query(query)
            self.assertEqual(plan.kind, "semantic")
            self.assertEqual(plan.text, focus)
        self.assertEqual(plan_query("Happy").kind, "text")
        self.assertEqual(plan_query("A Song About Love", metadata_names={"a song about love"}).kind, "text")
        self.assertEqual(plan_query("Bruno Mars").kind, "text")

    def test_theme_ranking_uses_semantic_signal_instead_of_metadata_overlap(self):
        docs = [song("good", "Dancing Together", "we celebrate life together"),
                song("bad", "My Happy Ending", "sadness and regret " * 20),
                song("neutral", "Other", "a different story")]
        semantic = SemanticFixture()
        config = load_config()
        config["mood"]["default_basis"] = "lyrics"
        engine = SearchEngine(docs, config, semantic=semantic)
        response = engine.search("lagu happy")
        self.assertEqual(response["results"][0]["track_id"], "good")
        self.assertEqual(response["query_type"], "semantic")
        self.assertIn("happiness", semantic.queries[-1])
        self.assertEqual(response["preferences"], {})
        self.assertFalse(response["pipeline"]["audio"])

    def test_theme_fallback_stays_explicit_when_semantic_is_missing(self):
        class Missing:
            ready = False

        docs = [song("x", "Happy", "happy happy"), song("y", "Other", "different")]
        response = SearchEngine(docs, load_config(), semantic=Missing()).search("lagu happy")
        self.assertTrue(response["pipeline"]["degraded"])
        self.assertTrue(response["warnings"])
        self.assertFalse(response["pipeline"]["semantic"])


class UserCorpusRegressionTests(unittest.TestCase):
    def test_users_bruno_mars_fragment_works_without_a_semantic_encoder(self):
        class Missing:
            ready = False

        engine = SearchEngine(load_docs(), load_config(), semantic=Missing())
        for query in ['make the stars look like there not shining', 'lirik "make the stars look like there not shining"']:
            result = engine.search(query)
            first = result["results"][0]
            self.assertEqual(first["title"], "Just the Way You Are")
            self.assertEqual(first["artist"], "Bruno Mars")
            self.assertEqual(first["lyric_match"]["kind"], "approximate")
            self.assertTrue(result["pipeline"]["degraded"])
