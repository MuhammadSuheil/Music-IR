"""Local, human-reviewed relevance collection. Never generates relevance grades."""
import csv
import hashlib
import io
import json
import random
import re
import sqlite3
import threading
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .catalog import track_summary
from .data import ROOT, corpus_hash, normalize, tokens
from .diagnostics import implementation_hash

DEFAULT_QUERIES = ROOT / "evaluation" / "queries.draft.jsonl"
DEFAULT_STORAGE = ROOT / "artifacts" / "benchmark"
MODES = ("E1", "E2", "E3", "E4", "E5", "AUTO")
RUBRIC = {0: "Tidak relevan", 1: "Sedikit terkait", 2: "Relevan", 3: "Sangat relevan / tepat"}


def sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def draft_queries(docs):
    """160 editable query drafts, 8 dev / 24 test in each category, zero labels."""
    by_artist = {}
    ordered = sorted(docs, key=lambda d: (-(d.get("track_popularity") or 0), d["track_id"]))
    for doc in ordered:
        artist = normalize(doc["track_artist"])
        if "," not in artist and len(tokens(doc.get("lyrics", ""))) >= 40:
            by_artist.setdefault(artist.casefold(), doc)
    selected = []
    for artist, title in (("Bruno Mars", "Just the Way You Are"), ("Coldplay", "Fix You")):
        doc = next((d for d in docs if d["track_artist"] == artist and d["track_name"] == title), None)
        if doc:
            selected.append(doc)
            by_artist.pop(artist.casefold(), None)
    selected.extend(list(by_artist.values())[:32 - len(selected)])
    if len(selected) != 32:
        raise ValueError("Draft 160 query memerlukan 32 artis berbeda dengan lirik yang cukup panjang.")
    pinned, rest = selected[:2], selected[2:]
    random.Random(42).shuffle(rest)
    selected = pinned + rest
    queries = []
    for index, doc in enumerate(selected):
        split = "dev" if index < 8 else "test"
        group = "artist-" + sha(doc["track_artist"].casefold())[:12]
        base = {"split": split, "group_id": group, "review_status": "draft",
                "source": "corpus_draft", "hint_track_ids": [doc["track_id"]]}
        words = tokens(doc["lyrics"])
        fragment = " ".join(words[len(words) // 3:len(words) // 3 + 8])
        if doc["track_name"] == "Just the Way You Are" and doc["track_artist"] == "Bruno Mars":
            fragment = "make the stars look like there not shining"
        for category, query, note in (
            ("title", doc["track_name"], "Cari judul; audit versi rekaman/cover yang juga relevan."),
            ("artist", doc["track_artist"], "Lagu artis ini, termasuk kolaborasi yang relevan."),
            ("lyrics", 'lirik "' + fragment + '"', "Periksa kutipan dengan lirik sumber dan rekaman. Hint bukan label otomatis."),
        ):
            queries.append({**base, "query_id": f"{category}-{index + 1:03}", "category": category,
                            "query": query, "intent_note": note})
    themes = [
        ("happy", "lagu happy", "songs about happiness and joy", "Ambigu: tetapkan apakah tema lirik bahagia atau bunyi musik ceria sebelum menyetujui."),
        ("breakup", "lagu tentang merindukan seseorang setelah putus cinta", "a song about missing an ex after a breakup", "Tema kerinduan setelah putus; baca lirik, jangan hanya judul."),
        ("loss", "lagu tentang kehilangan orang yang dicintai", "a song about grieving someone you love", "Tema kehilangan orang terkasih."),
        ("hope", "lagu tentang tetap berharap saat hidup sulit", "a song about keeping hope through hard times", "Tema harapan dalam kesulitan."),
        ("self", "lagu tentang menerima diri sendiri", "a song about accepting yourself", "Penerimaan diri."),
        ("nostalgia", "lagu tentang ingin kembali ke masa lalu", "a song about wishing to go back in time", "Nostalgia pada masa lalu."),
        ("friendship", "lagu tentang persahabatan yang selalu ada", "a song about friends supporting each other", "Persahabatan dan dukungan."),
        ("love", "lagu tentang baru jatuh cinta", "a song about falling in love", "Awal jatuh cinta."),
        ("distance", "lagu tentang cinta jarak jauh", "a song about a long distance relationship", "Hubungan jarak jauh."),
        ("betrayal", "lagu tentang dikhianati pasangan", "a song about being betrayed by a partner", "Pengkhianatan pasangan."),
        ("lonely", "lagu tentang merasa sendirian di keramaian", "a song about feeling lonely in a crowd", "Kesepian di tengah orang lain."),
        ("dream", "lagu tentang mengejar impian", "a song about chasing your dreams", "Mengejar impian."),
        ("regret", "lagu tentang menyesali kesalahan sendiri", "a song about regretting your mistakes", "Penyesalan atas kesalahan sendiri."),
        ("freedom", "lagu tentang ingin hidup bebas", "a song about wanting freedom", "Keinginan hidup bebas."),
        ("family", "lagu tentang merindukan rumah dan keluarga", "a song about missing home and family", "Kerinduan rumah/keluarga."),
        ("farewell", "lagu tentang mengucapkan selamat tinggal", "a song about saying goodbye", "Perpisahan."),
    ]
    audio = [
        ("tempo-120", "tempo > 120 BPM", "tempo di atas 120 BPM"),
        ("energy-low", "energi rendah", "energy low"),
        ("tempo-90", "tempo < 90 BPM", "tempo di bawah 90 BPM"),
        ("energy-high", "energi tinggi", "energy high"),
        ("tempo-100", "tempo >= 100 BPM", "tempo minimal 100 BPM"),
        ("energy-half", "energi <= 0,5", "energy at most 0.5"),
        ("valence-high", "valence > 0,7", "valence above 0.7"),
        ("acoustic", "acousticness >= 0,6", "acousticness minimal 0.6"),
        ("dance", "danceability > 0,7", "danceability di atas 0.7"),
        ("combo-fast", "tempo > 120 BPM dan energi > 0,7", "tempo above 120 BPM dan energy above 0.7"),
        ("combo-slow", "tempo < 100 BPM dan energi < 0,5", "tempo below 100 BPM dan energy below 0.5"),
        ("not-fast", "tempo tidak di atas 120 BPM", "tempo <= 120 BPM"),
        ("slow", "tempo lambat", "tempo slow"),
        ("fast", "tempo cepat", "tempo fast"),
        ("bruno-fast", "Bruno Mars dengan tempo > 120 BPM", "lagu Bruno Mars tempo di atas 120 BPM"),
        ("low-valence", "valence < 0,3", "valence below 0.3"),
    ]
    for category, groups in (("semantic", themes), ("audio", audio)):
        for index, group in enumerate(groups):
            name, first, second, *notes = group
            for variant, query in enumerate((first, second)):
                queries.append({"query_id": f"{category}-{index * 2 + variant + 1:03}", "query": query,
                    "category": category, "split": "dev" if index < 4 else "test", "group_id": f"{category}-{name}",
                    "review_status": "draft", "source": "authored_draft", "hint_track_ids": [],
                    "intent_note": notes[0] if notes else "Periksa batas numerik dan preferensi audio menggunakan nilai corpus."})
    return queries


class BenchmarkStore:
    def __init__(self, docs, queries_path=DEFAULT_QUERIES, directory=DEFAULT_STORAGE):
        self.docs = docs
        self.positions = {d["track_id"]: d for d in docs}
        self.queries_path, self.directory = Path(queries_path), Path(directory)
        self.corpus_sha = corpus_hash(docs)
        self.lock = threading.Lock()

    def queries(self):
        if not self.queries_path.exists():
            raise ValueError("Draft query belum dibuat. Jalankan: python -m music_ir benchmark-draft")
        rows = [json.loads(line) for line in self.queries_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        ids, groups = set(), {}
        for row in rows:
            if row["query_id"] in ids or row.get("split") not in {"dev", "test"} or not row.get("group_id"):
                raise ValueError("ID, split, atau group_id draft query tidak valid.")
            if row["group_id"] in groups and groups[row["group_id"]] != row["split"]:
                raise ValueError("group_id tidak boleh melintasi dev/test.")
            groups[row["group_id"]] = row["split"]
            ids.add(row["query_id"])
        return rows

    def identity(self):
        return sha({"corpus": self.corpus_sha, "queries": self.queries()})

    def query(self, query_id):
        row = next((q for q in self.queries() if q["query_id"] == query_id), None)
        if row is None:
            raise KeyError("Query benchmark tidak ditemukan.")
        return row

    @contextmanager
    def connect(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.directory / "reviews.sqlite3", timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS judgments (dataset TEXT, query_id TEXT, track_id TEXT, annotator TEXT, grade INTEGER, notes TEXT, updated TEXT, PRIMARY KEY(dataset,query_id,track_id,annotator))")
        db.execute("CREATE TABLE IF NOT EXISTS reviews (dataset TEXT, query_id TEXT, annotator TEXT, updated TEXT, PRIMARY KEY(dataset,query_id,annotator))")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def load_pools(self):
        path = self.directory / "pool.json"
        if not path.exists():
            return {"dataset": self.identity(), "queries": {}}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if data.get("dataset") == self.identity() else {"dataset": self.identity(), "queries": {}}

    def save_pools(self, pools):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "pool.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(pools, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def annotator(value):
        value = value.strip()
        if not re.fullmatch(r"\w[\w .-]{0,63}", value):
            raise ValueError("Isi nama/kode penilai (1–64 huruf/angka, spasi, titik, atau tanda hubung).")
        return value

    def judgments(self, query_id=None):
        with self.connect() as db:
            sql = "SELECT * FROM judgments WHERE dataset=?"
            args = [self.identity()]
            if query_id:
                sql += " AND query_id=?"
                args.append(query_id)
            return [dict(row) for row in db.execute(sql, args)]

    def summary(self):
        queries, pools = self.queries(), self.load_pools()["queries"]
        judged = self.judgments()
        with self.connect() as db:
            approved = {row[0] for row in db.execute("SELECT DISTINCT query_id FROM reviews WHERE dataset=?", (self.identity(),))}
        pairs = {}
        for item in judged:
            pairs.setdefault((item["query_id"], item["track_id"]), set()).add(item["grade"])
        result = []
        for query in queries:
            qid = query["query_id"]
            pool_ids = set(pools.get(qid, {}).get("track_ids", []))
            result.append({**query, "review_status": "approved" if qid in approved else "draft",
                "pool_count": len(pools.get(qid, {}).get("track_ids", [])),
                "judged_count": sum(key[0] == qid and key[1] in pool_ids for key in pairs),
                "conflicts": sum(key[0] == qid and len(grades) > 1 for key, grades in pairs.items())})
        return {"queries": result, "rubric": RUBRIC, "dataset_sha256": self.identity(),
                "total": len(result), "approved": len(approved), "judgments": len(judged),
                "splits": dict(Counter(q["split"] for q in queries)),
                "note": "Draft dan hint bukan label. Semua nilai relevansi harus berasal dari penilai manusia."}

    def prepare_pool(self, engine, query_id, modes=None, depth=10):
        query = self.query(query_id)
        modes = list(modes or (MODES if engine.semantic.ready else ("E1", "E2", "AUTO")))
        if not modes or any(mode not in MODES for mode in modes) or not 1 <= depth <= 100:
            raise ValueError("Mode pool atau depth (1–100) tidak valid.")
        if corpus_hash(engine.docs) != self.corpus_sha:
            raise ValueError("Corpus mesin berbeda dari benchmark.")
        tracks, runs = set(), {}
        for mode in dict.fromkeys(modes):
            response = engine.search(query["query"], mode, top_k=depth)
            ranking = [r["track_id"] for r in response["results"]]
            tracks.update(ranking)
            runs[mode] = {"ranking": ranking, "pipeline": response["pipeline"], "warnings": response["warnings"]}
        tracks.update(track_id for track_id in query.get("hint_track_ids", []) if track_id in self.positions)
        population = sorted(self.positions)
        tracks.update(random.Random(query_id).sample(population, min(2, len(population))))
        row = {"track_ids": sorted(tracks), "runs": runs, "depth": depth,
               "implementation_sha256": implementation_hash(), "config": json.loads(json.dumps(engine.config)),
               "corpus_sha256": self.corpus_sha, "created_utc": datetime.now(timezone.utc).isoformat()}
        with self.lock:
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                pools = self.load_pools()
                pools["queries"][query_id] = row
                self.save_pools(pools)
        return {"query_id": query_id, "pool_count": len(tracks), "modes": list(runs)}

    def candidates(self, query_id, annotator=""):
        query = self.query(query_id)
        pool = self.load_pools()["queries"].get(query_id)
        if pool is None:
            return {"query": query, "candidates": [], "prepared": False}
        own = {row["track_id"]: row for row in self.judgments(query_id) if row["annotator"] == annotator}
        ids = sorted(pool["track_ids"], key=lambda track_id: sha(query_id + ":" + track_id))
        return {"query": query, "prepared": True,
                "candidates": [{**track_summary(self.positions[track_id]),
                    "lyrics": self.positions[track_id].get("lyrics", ""),
                    "judgment": {"grade": own[track_id]["grade"], "notes": own[track_id]["notes"]} if track_id in own else None}
                    for track_id in ids],
                "pool_manifest": {key: pool[key] for key in ("depth", "created_utc", "implementation_sha256")},
                "note": "Urutan diacak deterministik; skor dan asal metode disembunyikan selama penilaian."}

    def review(self, query_id, annotator):
        self.query(query_id)
        annotator = self.annotator(annotator)
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO reviews VALUES (?,?,?,?)",
                       (self.identity(), query_id, annotator, datetime.now(timezone.utc).isoformat()))
        return {"query_id": query_id, "review_status": "approved", "annotator": annotator}

    def judge(self, query_id, track_id, annotator, grade, notes=""):
        self.query(query_id)
        annotator = self.annotator(annotator)
        if type(grade) is not int or grade not in range(4) or len(notes) > 2000:
            raise ValueError("Nilai harus bilangan bulat 0–3; catatan maksimal 2000 karakter.")
        pool = self.load_pools()["queries"].get(query_id, {})
        if track_id not in pool.get("track_ids", []):
            raise ValueError("Lagu tidak ada di pool query ini. Siapkan pool sebelum menilai.")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO judgments VALUES (?,?,?,?,?,?,?)", (self.identity(), query_id,
                       track_id, annotator, grade, notes, datetime.now(timezone.utc).isoformat()))
        return {"query_id": query_id, "track_id": track_id, "annotator": annotator, "grade": grade}

    def export(self, split="dev", query_ids=None):
        if split not in {"dev", "test"}:
            raise ValueError("Split harus dev atau test.")
        summary = self.summary()
        queries = [q for q in summary["queries"] if q["split"] == split and (query_ids is None or q["query_id"] in query_ids)]
        if not queries or query_ids is not None and set(query_ids) != {q["query_id"] for q in queries}:
            raise ValueError("Pilihan query tidak valid untuk split ini.")
        rows, writer_buffer = [], io.StringIO(newline="")
        writer = csv.writer(writer_buffer)
        writer.writerow(("query_id", "track_id", "relevance", "annotator"))
        judgments = self.judgments()
        for query in queries:
            qid = query["query_id"]
            selected = [j for j in judgments if j["query_id"] == qid]
            if query["review_status"] != "approved":
                raise ValueError(f"Tinjau dan setujui definisi query terlebih dahulu: {qid}")
            if query["conflicts"]:
                raise ValueError(f"Selesaikan perbedaan nilai antarpenilai sebelum ekspor: {qid}")
            if not query["pool_count"] or query["judged_count"] < query["pool_count"]:
                raise ValueError(f"Pool belum selesai dinilai: {qid} ({query['judged_count']}/{query['pool_count']})")
            if not any(j["grade"] >= 2 for j in selected):
                raise ValueError(f"Belum ada label relevan >=2; audit dahulu: {qid}")
            for item in selected:
                writer.writerow((qid, item["track_id"], item["grade"], item["annotator"]))
            rows.append({key: value for key, value in query.items() if key not in {"pool_count", "judged_count", "conflicts"}})
        return {"queries_jsonl": "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                "qrels_csv": writer_buffer.getvalue(), "manifest": {"dataset_sha256": self.identity(),
                "corpus_sha256": self.corpus_sha, "split": split, "query_ids": [q["query_id"] for q in queries],
                "policy": "human judgments only; conflicts must be resolved; unjudged=0 in runner",
                "judged_pairs": sum(q["judged_count"] for q in queries), "created_utc": datetime.now(timezone.utc).isoformat()}}
