import csv
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROCESSED = ROOT / "data" / "processed"
NUMERIC = ("energy", "tempo", "danceability", "loudness", "liveness", "valence",
           "speechiness", "track_popularity", "instrumentalness", "mode", "key",
           "duration_ms", "acousticness", "time_signature")
PLAYLIST = ("playlist_id", "playlist_name", "playlist_genre", "playlist_subgenre")


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(text)).split())


def tokens(text: str) -> list[str]:
    return re.findall(r"\w+", normalize(text).casefold(), flags=re.UNICODE)


def corpus_hash(docs: list[dict]) -> str:
    return hashlib.sha256(json.dumps(docs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def prepare(source: Path, output: Path = PROCESSED) -> dict:
    raw = source.read_bytes()
    with source.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        required = {"track_id", "track_name", "track_artist", "lyrics"}
        if not required.issubset(columns):
            raise ValueError(f"Kolom wajib tidak tersedia: {sorted(required - set(columns))}")
        rows = list(reader)
    if not rows:
        raise ValueError("CSV tidak memiliki dokumen lagu.")
    groups = defaultdict(list)
    for row in rows:
        if not row["track_id"].strip():
            raise ValueError("Ada track_id kosong; perbaiki sumber sebelum indexing.")
        groups[row["track_id"]].append(row)
    docs, conflicts = [], []
    for track_id, group in sorted(groups.items()):
        doc = {"track_id": track_id}
        for column in columns:
            if column == "track_id":
                continue
            values = list(dict.fromkeys(r[column] for r in group if r[column].strip()))
            if column in PLAYLIST:
                doc[column] = sorted({normalize(v) for v in values})
                continue
            if len(values) > 1:
                conflicts.append({"track_id": track_id, "field": column, "values": values})
            # Deterministic first nonempty value; conflicts remain in audit for review.
            value = values[0] if values else ""
            if column in NUMERIC:
                try:
                    import math
                    number = float(value)
                    doc[column] = number if math.isfinite(number) else None
                except ValueError:
                    doc[column] = None
            else:
                doc[column] = value
        for field in ("track_name", "track_artist", "lyrics"):
            doc[field + "_normalized"] = normalize(doc.get(field, ""))
        doc["lyrics_available"] = bool(doc.get("lyrics", "").strip())
        doc["lyrics_match_status"] = "unknown"
        docs.append(doc)
    audit = {
        "source_sha256": hashlib.sha256(raw).hexdigest(), "source_rows": len(rows),
        "source_columns": len(columns), "unique_tracks": len(docs),
        "extra_occurrences": len(rows) - len(docs),
        "tracks_without_lyrics": sum(not d["lyrics_available"] for d in docs),
        "short_lyrics_ids": [d["track_id"] for d in docs if d["lyrics_available"] and len(d["lyrics"].strip()) < 100],
        "replacement_character_ids": [d["track_id"] for d in docs if any("\ufffd" in str(d.get(f, "")) for f in ("track_name", "track_artist", "lyrics"))],
        "conflicts": conflicts, "corpus_sha256": corpus_hash(docs),
        "merge_policy": "first nonempty value; playlist fields union; conflicts audited",
    }
    import pandas as pd
    snapshot = output.parent / "raw" / (audit["source_sha256"] + ".csv")
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if not snapshot.exists():
        snapshot.write_bytes(raw)
    audit["source_snapshot"] = str(snapshot.resolve())
    output.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(docs).to_parquet(output / "corpus.parquet", index=False)
    (output / "corpus.json").write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    (output / "audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    return audit


def load_docs() -> list[dict]:
    path = PROCESSED / "corpus.json"
    if not path.exists():
        raise FileNotFoundError("Corpus belum dibuat. Jalankan: python -m music_ir prepare --csv <path>")
    return json.loads(path.read_text(encoding="utf-8"))
