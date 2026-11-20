import json
import hashlib
import os
import re
import time
import threading

import numpy as np

from .data import ROOT, corpus_hash

ARTIFACTS = ROOT / "artifacts" / "semantic"


def load_model(config, local_only=False):
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError('Dependensi semantik belum tersedia. Install: pip install -e ".[semantic]"') from exc
    import torch
    # Small CPU workloads can become slower when every logical core is used.
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    return SentenceTransformer(config["model_name"], revision=config["model_revision"],
                               cache_folder=str(ROOT / ".cache" / "huggingface"),
                               local_files_only=local_only)


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    for attempt in range(5):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(.02)


def build_embeddings(docs, config, batch_size=4, local_only=False):
    from filelock import FileLock
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with FileLock(str(ARTIFACTS / "build.lock"), timeout=0):
        try:
            return _build_embeddings(docs, config, batch_size, local_only)
        except BaseException as exc:
            path = ARTIFACTS / "progress.json"
            progress = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
            progress.update(state="interrupted" if isinstance(exc, KeyboardInterrupt) else "error", error=str(exc))
            write_json(path, progress)
            raise


def _build_embeddings(docs, config, batch_size, local_only):
    if batch_size < 1:
        raise ValueError("batch_size harus positif.")
    started = time.perf_counter()
    # Resolve a mutable branch to an immutable commit before encoding any document.
    revision = config["model_revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        if local_only:
            raise ValueError("Mode offline memerlukan model_revision berupa commit 40 karakter.")
        from huggingface_hub import model_info
        revision = model_info(config["model_name"], revision=revision).sha
    pinned = {**config, "model_revision": revision}
    write_json(ARTIFACTS / "progress.json", {"state": "loading_model", "completed": 0, "total": len(docs)})
    model = load_model(pinned, local_only=local_only)
    texts, owners, chunked, lengths = [], [], [], []
    for position, doc in enumerate(docs):
        text = f"Judul: {doc['track_name']}\nArtis: {doc['track_artist']}\nLirik: {doc.get('lyrics', '')}"
        ids = model.tokenizer.encode(text, add_special_tokens=False)
        if len(ids) + model.tokenizer.num_special_tokens_to_add() > 8192:
            chunks = [model.tokenizer.decode(ids[i:i + 512]) for i in range(0, len(ids), 448)]
            texts.extend(chunks)
            owners.extend([position] * len(chunks))
            lengths.extend([512] * len(chunks))
            chunked.append(doc["track_id"])
        else:
            texts.append(text)
            owners.append(position)
            lengths.append(len(ids))
    order = sorted(range(len(texts)), key=lambda i: (-lengths[i], i))
    signature = {"model_name": config["model_name"], "model_revision": revision,
                 "corpus_sha256": corpus_hash(docs),
                 "order_sha256": hashlib.sha256(json.dumps(order).encode()).hexdigest(),
                 "texts_sha256": hashlib.sha256(json.dumps(texts, ensure_ascii=False).encode()).hexdigest()}
    checkpoint_path = ARTIFACTS / "checkpoint.json"
    partial_path = ARTIFACTS / "partial.npy"
    previous = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {}
    done = 0
    dimension = model.get_sentence_embedding_dimension()
    if previous.get("signature") == signature and partial_path.exists():
        encoded = np.lib.format.open_memmap(partial_path, mode="r+")
        done = previous["done"]
        if encoded.shape != (len(texts), dimension) or not 0 <= done <= len(texts):
            raise RuntimeError("Checkpoint embedding tidak valid; simpan ulang artefak sebelum melanjutkan.")
    else:
        encoded = np.lib.format.open_memmap(partial_path, mode="w+", dtype=np.float32, shape=(len(texts), dimension))
    while done < len(order):
        selected = order[done:done + batch_size]
        batch = model.encode([texts[i] for i in selected], batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)
        encoded[selected] = batch
        encoded.flush()
        done += len(selected)
        write_json(checkpoint_path, {"signature": signature, "done": done})
        write_json(ARTIFACTS / "progress.json", {"state": "encoding", "completed": done, "total": len(texts),
                                               "elapsed_seconds": round(time.perf_counter() - started, 1),
                                               "device": str(model.device)})
        print(f"Embedding {done}/{len(texts)} potongan selesai", flush=True)
    vectors = np.zeros((len(docs), encoded.shape[1]), dtype=np.float32)
    counts = np.zeros(len(docs), dtype=np.float32)
    for owner, vector in zip(owners, encoded):
        vectors[owner] += vector
        counts[owner] += 1
    vectors /= counts[:, None]
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    np.save(ARTIFACTS / "vectors.npy", np.asarray(vectors, dtype=np.float32))
    metadata = {"model_name": config["model_name"], "model_revision": revision,
                "corpus_sha256": corpus_hash(docs), "track_ids": [d["track_id"] for d in docs],
                "chunked_ids": chunked, "representation": "Judul: title\\nArtis: artist\\nLirik: lyrics",
                "offline_seconds": round(time.perf_counter() - started, 2), "batch_size": batch_size,
                "device": str(model.device)}
    write_json(ARTIFACTS / "metadata.json", metadata)
    write_json(ARTIFACTS / "progress.json", {"state": "ready", "completed": len(texts), "total": len(texts)})
    return metadata


class SemanticIndex:
    def __init__(self, docs, config):
        self.docs, self.config, self.model = docs, config, None
        self.lock = threading.RLock()
        self.vectors = None
        meta_path = ARTIFACTS / "metadata.json"
        if meta_path.exists() and (ARTIFACTS / "vectors.npy").exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            revision_ok = config["model_revision"] == "main" or config["model_revision"] == meta["model_revision"]
            if meta["corpus_sha256"] == corpus_hash(docs) and meta["track_ids"] == [d["track_id"] for d in docs] and meta["model_name"] == config["model_name"] and revision_ok:
                vectors = np.load(ARTIFACTS / "vectors.npy", allow_pickle=False)
                if vectors.ndim == 2 and vectors.shape == (len(docs), 1024) and np.isfinite(vectors).all() and np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-4):
                    self.vectors = vectors
                    self.config = {**config, "model_revision": meta["model_revision"]}

    @property
    def ready(self):
        return self.vectors is not None

    def warmup(self):
        if not self.ready:
            raise RuntimeError("Embedding BGE-M3 belum tersedia atau tidak cocok dengan corpus. Jalankan: python -m music_ir embed")
        with self.lock:
            if self.model is None:
                self.model = load_model(self.config, local_only=True)
                self.model.encode(["pemanasan"], normalize_embeddings=True)

    def scores(self, query):
        with self.lock:
            self.warmup()
            vector = self.model.encode([query], normalize_embeddings=True)[0]
            return np.clip(self.vectors @ vector, -1, 1)

    def passage_scores(self, query, candidates, profile=None):
        from .passages import score_passages
        with self.lock:
            self.warmup()
            return score_passages(self.model, self.config, self.docs, candidates, query, ARTIFACTS / "passages.sqlite3", profile=profile)
