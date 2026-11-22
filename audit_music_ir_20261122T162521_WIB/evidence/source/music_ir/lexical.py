import json
import math
import os
from collections import Counter
from urllib.request import Request, urlopen

import numpy as np

from .data import tokens

FIELDS = ("track_name", "track_artist", "lyrics")
INDEX = "music-ir-v1"


class LocalBM25:
    """Portable reference implementation; not equivalent to the Lucene analyzer."""

    def __init__(self, docs, config):
        self.config = config
        self.fields = {}
        for field in (*FIELDS, "combined"):
            texts = [" ".join(d.get(f, "") for f in FIELDS) if field == "combined" else d.get(field, "") for d in docs]
            counts = [Counter(tokens(t)) for t in texts]
            lengths = np.array([sum(c.values()) for c in counts], dtype=float)
            df = Counter(t for c in counts for t in c)
            self.fields[field] = (counts, lengths, float(lengths.mean()) or 1, df)

    def field_scores(self, query, field):
        counts, lengths, avg, df = self.fields[field]
        result = np.zeros(len(counts))
        k1, b = self.config["bm25_k1"], self.config["bm25_b"]
        for token in set(tokens(query)):
            freq = np.array([c[token] for c in counts], dtype=float)
            idf = math.log(1 + (len(counts) - df[token] + .5) / (df[token] + .5))
            result += idf * freq * (k1 + 1) / (freq + k1 * (1 - b + b * lengths / avg))
        return result

    def scores(self, query, combined=False):
        if combined:
            return self.field_scores(query, "combined")
        return sum(w * self.field_scores(query, f) for f, w in zip(FIELDS, self.config["field_weights"]))


class ElasticsearchBM25:
    def __init__(self, docs, config):
        self.docs, self.config = docs, config
        self.url = os.environ.get("ELASTICSEARCH_URL", "http://127.0.0.1:9200").rstrip("/")
        if not self.url.startswith(("http://localhost:", "http://127.0.0.1:")):
            raise ValueError("Prototipe Elasticsearch ini hanya dikonfigurasi untuk server lokal.")
        self.positions = {d["track_id"]: i for i, d in enumerate(docs)}

    def request(self, method, path, payload=None, ndjson=None):
        body = ndjson.encode() if ndjson is not None else (json.dumps(payload).encode() if payload is not None else None)
        headers = {"Content-Type": "application/x-ndjson" if ndjson is not None else "application/json"}
        req = Request(self.url + path, data=body, method=method, headers=headers)
        with urlopen(req, timeout=60) as response:
            return json.load(response)

    def build(self):
        from .data import corpus_hash
        # Versioned physical index: rebuilding never deletes an existing index.
        from datetime import datetime, timezone
        name = INDEX + "-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        self.request("PUT", "/" + name, {
            "settings": {"number_of_shards": 1, "number_of_replicas": 0,
                         "similarity": {"project_bm25": {"type": "BM25", "k1": self.config["bm25_k1"], "b": self.config["bm25_b"]}},
                         "analysis": {"analyzer": {"music_text": {"type": "custom", "tokenizer": "standard", "filter": ["lowercase"]}}}},
            "mappings": {"_meta": {"corpus_sha256": corpus_hash(self.docs), "k1": self.config["bm25_k1"], "b": self.config["bm25_b"]},
                         "properties": {"track_id": {"type": "keyword"}, **{f: {"type": "text", "analyzer": "music_text", "similarity": "project_bm25"} for f in (*FIELDS, "combined")}}}
        })
        for start in range(0, len(self.docs), 200):
            lines = []
            for doc in self.docs[start:start + 200]:
                lines.extend([json.dumps({"index": {"_index": name, "_id": doc["track_id"]}}), json.dumps({"track_id": doc["track_id"], **{f: doc.get(f + "_normalized", doc.get(f, "")) for f in FIELDS}, "combined": " ".join(doc.get(f + "_normalized", doc.get(f, "")) for f in FIELDS)})])
            result = self.request("POST", "/_bulk", ndjson="\n".join(lines) + "\n")
            if result.get("errors"):
                raise RuntimeError("Elasticsearch bulk indexing gagal; alias belum diubah.")
        self.request("POST", "/" + name + "/_refresh")
        self.request("POST", "/_aliases", {"actions": [{"remove": {"index": INDEX + "-*", "alias": INDEX, "must_exist": False}}, {"add": {"index": name, "alias": INDEX}}]})
        return name

    def validate(self):
        from .data import corpus_hash
        mapping = self.request("GET", "/" + INDEX + "/_mapping")
        meta = next(iter(mapping.values()))["mappings"].get("_meta", {})
        if meta != {"corpus_sha256": corpus_hash(self.docs), "k1": self.config["bm25_k1"], "b": self.config["bm25_b"]}:
            raise RuntimeError("Indeks Elasticsearch berbeda dari corpus/config; buat ulang indeks.")

    def scores(self, query, combined=False):
        self.validate()
        match = {"match": {"combined": query}} if combined else {"bool": {"should": [{"match": {f: {"query": query, "boost": w}}} for f, w in zip(FIELDS, self.config["field_weights"]) if w > 0], "minimum_should_match": 1}}
        result = self.request("POST", "/" + INDEX + "/_search", {"size": len(self.docs), "query": match, "_source": ["track_id"]})
        scores = np.zeros(len(self.docs))
        for hit in result["hits"]["hits"]:
            scores[self.positions[hit["_source"]["track_id"]]] = hit["_score"]
        return scores
