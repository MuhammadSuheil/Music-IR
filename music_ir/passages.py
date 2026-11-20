"""Cached lyric-only evidence using the existing frozen semantic encoder."""
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import numpy as np


COUNTER_THEMES = {
    "romance": ["Lyrics about partying, drinking and enjoying nightlife.",
                "Lyrics about violence, enemies, money and showing off status."],
    "moving_on": ["Lyrics celebrating a happy romantic relationship, mutual affection and being in love with a current partner.",
                  "Lyrics about looking for a new relationship and wanting to meet someone new."],
}

# A narrow, inspectable support rule for the breakup facet. It is not a
# universal emotion/language classifier; unsupported matches remain related.
LOSS_CUES = re.compile(
    r"\b(?:breakup|break up|broken heart|heartbreak|goodbye|gone|left|leaving|lost|regret|"
    r"miss(?:ing)? (?:you|her|him)|without (?:you|her|him)|used to|move on|over you|"
    r"let (?:you|her|him) go|walk(?:ed)? (?:away|out)|"
    r"se fue|te fuiste|olvidar(?:te|la|lo)?|perderte|extraño|llorar|sin ti|ya no|"
    r"sans toi|oublier|perdu|adieu|larmes|"
    r"mantan|putus|berpisah|kehilangan|meninggalkan|tanpamu|merindukan|melupakan|kenangan)\b", re.I)


def topic_cues(text, profile):
    return list(dict.fromkeys(m.group().casefold() for m in LOSS_CUES.finditer(text))) if profile == "moving_on" else []


def chunks(text, size=160, overlap=40):
    words = list(re.finditer(r"\S+", text))
    result = []
    for start in range(0, len(words), size - overlap):
        end = min(start + size, len(words))
        result.append(text[words[start].start():words[end - 1].end()])
        if end == len(words):
            break
    return list(dict.fromkeys(result))


def score_passages(model, config, docs, candidates, query, cache_path, profile=None):
    texts, owners = [], []
    for index in candidates:
        for text in chunks(docs[index].get("lyrics", "")):
            texts.append(text)
            owners.append(index)
    if not texts:
        return {}, {"passages": 0, "encoded": 0, "cache_hits": 0}
    signature = json.dumps([config["model_name"], config["model_revision"], "lyric-passages-v1"])
    keys = [hashlib.sha256((signature + "\0" + text).encode()).hexdigest() for text in texts]
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    vectors = {}
    with closing(sqlite3.connect(cache_path, timeout=30)) as db, db:
        db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector BLOB NOT NULL)")
        for cache_key in set(keys):
            row = db.execute("SELECT vector FROM vectors WHERE key=?", (cache_key,)).fetchone()
            if row:
                vector = np.frombuffer(row[0], dtype=np.float32)
                if vector.shape == (model.get_sentence_embedding_dimension(),) and np.isfinite(vector).all() and np.isclose(np.linalg.norm(vector), 1, atol=1e-4):
                    vectors[cache_key] = vector
        missing = {cache_key: text for cache_key, text in zip(keys, texts) if cache_key not in vectors}
        if missing:
            encoded = model.encode(list(missing.values()), batch_size=4, normalize_embeddings=True, show_progress_bar=False)
            encoded = np.asarray(encoded, dtype=np.float32)
            if encoded.shape != (len(missing), model.get_sentence_embedding_dimension()) or not np.isfinite(encoded).all():
                raise RuntimeError("Embedding bagian lirik tidak valid.")
            for cache_key, vector in zip(missing, encoded):
                vectors[cache_key] = vector
                db.execute("INSERT OR REPLACE INTO vectors VALUES (?, ?)", (cache_key, vector.tobytes()))
    counter_themes = COUNTER_THEMES.get(profile, [])
    query_vectors = model.encode([query, *counter_themes], normalize_embeddings=True, show_progress_bar=False)
    matrix = np.array([vectors[k] for k in keys])
    similarities = np.clip(matrix @ query_vectors[0], -1, 1)
    negative = np.max(np.clip(matrix @ query_vectors[1:].T, -1, 1), axis=1) if counter_themes else None
    ranking = (similarities - negative) / 2 if negative is not None else similarities
    evidence = {}
    for index in candidates:
        positions = sorted((i for i, owner in enumerate(owners) if owner == index), key=lambda i: (-float(ranking[i]), i))
        matches = [(float(similarities[i]), texts[i]) for i in positions]
        if matches:
            # Repeated/isolated phrases must not be the only semantic signal.
            aggregate = .7 * matches[0][0] + .3 * float(np.mean([score for score, _ in matches[:3]]))
            ranked_cosine = .7 * float(ranking[positions[0]]) + .3 * float(np.mean(ranking[positions[:3]]))
            evidence[index] = {"cosine": aggregate, "ranking_cosine": ranked_cosine, "best_cosine": matches[0][0], "passages": len(matches),
                               "text": matches[0][1], "source": "lyrics_only", "method": "bge_passages_contrast_v1" if counter_themes else "bge_passages_v1",
                               "profile": profile, "counter_themes": counter_themes,
                               "counter_cosine": aggregate - 2 * ranked_cosine if counter_themes else None,
                               "topic_cues": topic_cues(docs[index].get("lyrics", ""), profile)}
    return evidence, {"passages": len(texts), "encoded": len(missing), "cache_hits": len(set(keys)) - len(missing)}
