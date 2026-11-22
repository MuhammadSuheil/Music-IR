import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from music_ir.engine import load_config
from music_ir import semantic


@unittest.skipUnless(importlib.util.find_spec("filelock"), "Checkpoint memerlukan dependensi semantic")
class CheckpointTests(unittest.TestCase):
    def test_interrupted_build_resumes_without_reencoding_completed_text(self):
        class Tokenizer:
            def encode(self, text, **kwargs):
                return list(range(len(text.split())))
            def num_special_tokens_to_add(self):
                return 2

        class Encoder:
            device = "cpu"
            tokenizer = Tokenizer()
            def __init__(self, fail=False):
                self.calls = []
                self.fail = fail
            def get_sentence_embedding_dimension(self):
                return 1024
            def encode(self, texts, **kwargs):
                self.calls.extend(texts)
                if self.fail and len(self.calls) == 2:
                    raise RuntimeError("fixture interrupted")
                result = np.zeros((len(texts), 1024), dtype=np.float32)
                result[:, 0] = 1
                return result

        docs = [{"track_id": str(i), "track_name": "Title " + str(i), "track_artist": "A", "lyrics": "words " * (i + 1)} for i in range(3)]
        first, resumed = Encoder(fail=True), Encoder()
        with tempfile.TemporaryDirectory() as directory, patch.object(semantic, "ARTIFACTS", Path(directory)):
            with patch.object(semantic, "load_model", return_value=first):
                with self.assertRaisesRegex(RuntimeError, "fixture"):
                    semantic.build_embeddings(docs, load_config(), batch_size=1, local_only=True)
            checkpoint = json.loads((Path(directory) / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["done"], 1)
            with patch.object(semantic, "load_model", return_value=resumed):
                semantic.build_embeddings(docs, load_config(), batch_size=1, local_only=True)
            self.assertEqual(len(resumed.calls), 2)
            self.assertNotIn(first.calls[0], resumed.calls)
            self.assertTrue(semantic.SemanticIndex(docs, load_config()).ready)
            self.assertEqual(json.loads((Path(directory) / "progress.json").read_text())["state"], "ready")
            docs[0]["lyrics"] = "changed corpus"
            self.assertFalse(semantic.SemanticIndex(docs, load_config()).ready)
