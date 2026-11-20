import json
import time
import sqlite3

import numpy as np

from .audio import Intent, audio_scores, parse
from .data import ROOT, load_docs, normalize, tokens
from .lexical import ElasticsearchBM25, LocalBM25
from .semantic import SemanticIndex
from .catalog import track_summary
from .lyrics import LyricIndex
from .query import QueryPlan, plan_query
from .mood import apply_mood
from .metadata import MetadataIndex


def load_config():
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if len(config["field_weights"]) != 3 or any(w < 0 for w in config["field_weights"]) or not any(config["field_weights"]):
        raise ValueError("field_weights harus berisi 3 bobot nonnegatif, minimal satu positif.")
    if len(config["text_weights"]) != 5 or any(w < 0 for w in config["text_weights"]) or not np.isclose(sum(config["text_weights"]), 1):
        raise ValueError("text_weights harus berisi 5 bobot nonnegatif dengan jumlah 1.")
    if not 0 <= config["audio_weight"] <= 1 or not 1 <= config["candidate_limit"] <= 100:
        raise ValueError("audio_weight harus 0–1 dan candidate_limit harus 1–100.")
    mood = config.get("mood", {})
    if mood.get("default_basis", "both") not in {"lyrics", "audio", "both"} or any(
        not isinstance(mood.get(key, .5), (int, float)) or not 0 <= mood.get(key, .5) <= 1
        for key in ("sad_max_valence", "sad_max_energy", "happy_min_valence")):
        raise ValueError("Konfigurasi mood tidak valid; batas valence/energy harus 0–1.")
    theme = config.get("theme", {})
    if not 1 <= theme.get("candidate_limit", 24) <= 100 or not 0 <= theme.get("document_weight", .4) <= 1:
        raise ValueError("Konfigurasi theme tidak valid.")
    return config


def overlap(query, text):
    a, b = set(tokens(query)), set(tokens(text))
    if not a:
        return 0.
    exact = normalize(query).casefold() == normalize(text).casefold()
    return max(float(exact), len(a & b) / max(len(a | b), 1))


def phrase_match(query, text):
    q, t = tokens(query), tokens(text)
    return float(len(q) >= 2 and any(t[i:i + len(q)] == q for i in range(len(t) - len(q) + 1)))


class SearchEngine:
    def __init__(self, docs=None, config=None, backend="local", semantic=None):
        self.docs = docs if docs is not None else load_docs()
        self.config = config if config is not None else load_config()
        if backend not in {"local", "elasticsearch"}:
            raise ValueError("Backend harus local atau elasticsearch.")
        self.backend = backend
        self.lexical = (LocalBM25 if backend == "local" else ElasticsearchBM25)(self.docs, self.config)
        self.semantic = semantic if semantic is not None else SemanticIndex(self.docs, self.config)
        self.lyrics = None
        self.metadata = MetadataIndex(self.docs)
        self.metadata_names = {normalize(name).casefold() for doc in self.docs
                               for name in (doc["track_name"], doc["track_artist"], *doc["track_artist"].split(",")) if normalize(name)}

    def status(self):
        self.refresh_semantic()
        from .semantic import ARTIFACTS
        progress_path = ARTIFACTS / "progress.json"
        progress = json.loads(progress_path.read_text(encoding="utf-8")) if progress_path.exists() else None
        return {"documents": len(self.docs), "without_lyrics": sum(not d["lyrics_available"] for d in self.docs),
                "lexical_backend": self.backend, "semantic_ready": self.semantic.ready,
                "default_mode": "AUTO",
                "embedding_progress": progress,
                "tuned": self.config.get("tuned", False)}

    def refresh_semantic(self):
        if isinstance(self.semantic, SemanticIndex) and not self.semantic.ready:
            self.semantic = SemanticIndex(self.docs, self.config)

    def ranked(self, scores, allowed=None, positive=False):
        candidates = range(len(self.docs)) if allowed is None else allowed
        return sorted((i for i in candidates if not positive or scores[i] > 0), key=lambda i: (-float(scores[i]), self.docs[i]["track_id"]))[:self.config["candidate_limit"]]

    def search(self, query, mode="AUTO", top_k=10, trace=False, inspect_track_id=None, mood_basis=None):
        if mode not in {"AUTO", "E1", "E2", "E3", "E4", "E5"}:
            raise ValueError("Konfigurasi pencarian harus AUTO atau E1–E5.")
        if not 1 <= top_k <= 100:
            raise ValueError("top_k harus 1–100.")
        if mood_basis is not None and mode != "AUTO":
            raise ValueError("Pilihan mood hanya tersedia dalam mode AUTO.")
        started = time.perf_counter()
        wall_started = started
        stage_started = started
        timings = {}
        automatic = mode == "AUTO"
        raw_plan = plan_query(query, metadata_names=self.metadata_names, metadata=self.metadata) if automatic else None
        if raw_plan is not None and raw_plan.kind == "lyrics":
            # Words inside a lyric quotation are literal, including audio words.
            intent = parse(raw_plan.audio_text) if tokens(raw_plan.audio_text) else Intent(raw_plan.text)
            plan = raw_plan
        else:
            intent = parse(query)
            plan = plan_query(intent.text, query, self.metadata_names, self.metadata) if automatic and intent.text else None
        detected_lyrics = None
        if plan is not None and plan.catalog_match and plan.catalog_match["method"] == "approximate":
            # Direct lyric evidence outranks a guessed title for unprefixed text.
            if not query.casefold().startswith(("judul ", "lagu berjudul ", "song titled ")):
                if self.lyrics is None:
                    self.lyrics = LyricIndex(self.docs)
                detected_lyrics = self.lyrics.match(plan.text)
                if any(match.kind == "exact" for match in detected_lyrics.values()):
                    plan = QueryPlan(plan.text, "lyrics", plan.text)
        if plan is not None:
            intent.text = plan.text
        mood = apply_mood(intent, plan, self.config, mood_basis) if automatic else None
        catalog_match = plan.catalog_match if plan else None
        structured = catalog_match is not None
        semantic_query = plan.semantic_text if plan is not None else intent.text
        lyric_matches = {}
        if automatic and intent.text and plan.kind not in {"semantic", "artist", "genre"}:
            if self.lyrics is None:
                self.lyrics = LyricIndex(self.docs)
            lyric_matches = detected_lyrics if detected_lyrics is not None else self.lyrics.match(intent.text)
        query_type = "audio" if not intent.text else plan.kind if structured else "lyrics" if lyric_matches else plan.kind if plan else "text"
        use_audio = mode in {"AUTO", "E5"} and intent.active
        hard_audio_only = not intent.text and use_audio and not intent.preferences
        filter_only = automatic and hard_audio_only
        popularity_ties = structured or filter_only
        rerank = mode in {"AUTO", "E4", "E5"}
        needs_semantic = bool(intent.text) and not structured
        use_semantic = needs_semantic and mode in {"AUTO", "E3", "E4", "E5"}
        use_lexical = bool(intent.text) and not structured
        warnings = []
        timings["planning_and_lyrics"] = (time.perf_counter() - stage_started) * 1000
        stage_started = time.perf_counter()
        loading_ms = 0.
        if plan is not None and plan.kind == "lyrics" and not lyric_matches:
            warnings.append("Belum ditemukan potongan lirik yang cukup mirip. Hasil berikut memakai kecocokan kata atau makna, bukan kecocokan kutipan yang terverifikasi.")
        n = len(self.docs)
        cosine = np.zeros(n)
        # Model loading is an offline/startup cost, excluded from online latency.
        if use_semantic:
            self.refresh_semantic()
            if automatic and not self.semantic.ready:
                use_semantic = False
                warnings.append("Pencarian semantik belum tersedia: embedding belum siap atau tidak cocok dengan corpus/model. "
                                "Hasil memakai kata kunci dan fitur audio yang diminta. Jalankan: python -m music_ir embed")
            else:
                try:
                    before_loading = time.perf_counter()
                    try:
                        self.semantic.warmup()
                    finally:
                        loading = time.perf_counter() - before_loading
                        started += loading
                        loading_ms += loading * 1000
                    cosine = self.semantic.scores(semantic_query)
                except (RuntimeError, OSError, ImportError):
                    if not automatic:
                        raise
                    use_semantic = False
                    warnings.append("Pencarian semantik gagal dijalankan. Hasil memakai kata kunci dan fitur audio yang diminta. "
                                    "Periksa dependensi semantik dan cache model BGE-M3.")
        features = None
        timings["model_loading"] = loading_ms
        timings["semantic_query"] = max(0., (time.perf_counter() - stage_started) * 1000 - loading_ms)
        stage_started = time.perf_counter()
        bm = self.lexical.scores(intent.text, combined=mode == "E1") if use_lexical else np.zeros(n)
        timings["lexical"] = (time.perf_counter() - stage_started) * 1000
        stage_started = time.perf_counter()
        mask, audio = audio_scores(self.docs, intent)
        metadata_mask = np.array([d["track_id"] in catalog_match["track_ids"] for d in self.docs]) if structured else np.ones(n, dtype=bool)
        allowed = np.flatnonzero(mask & metadata_mask) if automatic and (use_audio or structured) else None
        lists = [self.ranked(bm, allowed, positive=True)] if use_lexical else []
        source_names = ["lexical"] if use_lexical else []
        if structured:
            lists.append(sorted(allowed, key=lambda i: (-(self.docs[i].get("track_popularity") or 0), self.docs[i]["track_id"]))[:self.config["candidate_limit"]])
            source_names.append("metadata")
        if use_semantic:
            lists.append(self.ranked(cosine, allowed))
            source_names.append("semantic")
        if lyric_matches and not structured:
            lists.append(sorted((i for i in lyric_matches if metadata_mask[i] and (not use_audio or mask[i])), key=lambda i: (lyric_matches[i].kind != "exact", -lyric_matches[i].similarity, self.docs[i]["track_id"])))
            source_names.append("lyrics")
        if use_audio:
            audio_allowed = np.flatnonzero(mask & metadata_mask)
            if automatic and not intent.preferences:
                audio_ranking = sorted(audio_allowed, key=lambda i: (-float(audio[i]), -(self.docs[i].get("track_popularity") or 0), self.docs[i]["track_id"]))[:self.config["candidate_limit"]]
            else:
                audio_ranking = self.ranked(audio, audio_allowed)
            lists.append(audio_ranking)
            source_names.append("audio")
        fusion = np.zeros(n)
        union = set()
        for ranking in lists:
            for rank, i in enumerate(ranking, 1):
                union.add(i)
                fusion[i] += 1 / (self.config["rrf_constant"] + rank)
        retrieved = set(union) if trace else None
        if use_audio:
            union = {i for i in union if mask[i]}
        if mode in {"E1", "E2"}:
            candidates = lists[0] if lists else []
            final = bm
        else:
            candidates = self.ranked(fusion, union)
            if lyric_matches and not structured:
                # Reserve the candidate budget for directly evidenced lyric hits.
                priority = sorted((i for i in lyric_matches if i in union),
                                  key=lambda i: (lyric_matches[i].kind != "exact", -lyric_matches[i].similarity, -fusion[i], self.docs[i]["track_id"]))[:self.config["candidate_limit"]]
                candidates = (priority + [i for i in candidates if i not in lyric_matches])[:self.config["candidate_limit"]]
            final = fusion.copy()
        timings["fusion_and_filters"] = (time.perf_counter() - stage_started) * 1000
        theme_evidence = {}
        theme_mix = self.config.get("theme", {}).get("document_weight", .4)
        passage_stats = {"passages": 0, "encoded": 0, "cache_hits": 0}
        passage_degraded = False
        if automatic and query_type == "semantic" and use_semantic:
            stage = time.perf_counter()
            if hasattr(self.semantic, "passage_scores"):
                candidates = candidates[:self.config.get("theme", {}).get("candidate_limit", 24)]
                try:
                    theme_evidence, passage_stats = self.semantic.passage_scores(semantic_query, candidates, profile=plan.theme_profile)
                except (RuntimeError, OSError, ImportError, sqlite3.Error):
                    passage_degraded = True
                    warnings.append("Pemeriksaan bagian lirik gagal; urutan tema memakai embedding lagu.")
            timings["lyric_passages"] = (time.perf_counter() - stage) * 1000
        before = list(candidates) if trace else None
        stage_started = time.perf_counter()
        weights = np.array(self.config["text_weights"], dtype=float)
        text_score = np.zeros(n)
        weight = 0.
        bonuses = {}
        if rerank and candidates:
            normalized_bm = np.zeros(n)
            span = np.ptp(bm[candidates])
            if span > 0:
                normalized_bm[candidates] = (bm[candidates] - bm[candidates].min()) / span
            features = [normalized_bm, (cosine + 1) / 2 if use_semantic else np.zeros(n), np.zeros(n), np.zeros(n), np.zeros(n)]
            for i in candidates:
                features[2][i] = overlap(intent.text, self.docs[i]["track_name"])
                features[3][i] = overlap(intent.text, self.docs[i]["track_artist"])
                features[4][i] = phrase_match(intent.text, self.docs[i].get("lyrics", ""))
            if automatic and not use_semantic:
                # An unavailable cosine must contribute neither a constant nor weight.
                weights[1] = 0
                weights = weights / weights.sum() if weights.sum() else np.array([1., 0., 0., 0., 0.])
            text_score = sum(w * feature for w, feature in zip(weights, features)) if intent.text else np.zeros(n)
            if automatic and query_type == "semantic" and use_semantic:
                # Keyword min-max scores must not override meaning-only queries.
                text_score = ((cosine + 1) / 2).astype(float)
                for i in candidates:
                    if i in theme_evidence:
                        evidence = theme_evidence[i]
                        text_score[i] = theme_mix * text_score[i] + (1 - theme_mix) * (evidence.get("ranking_cosine", evidence["cosine"]) + 1) / 2
            if structured:
                text_score[candidates] = catalog_match["similarity"]
            weight = (self.config["audio_weight"] if intent.text else 1) if use_audio else 0
            final = (1 - weight) * text_score + weight * audio
            for i in candidates:
                if i in lyric_matches and not structured:
                    match = lyric_matches[i]
                    # Explicit ranking policy, not a probability or tuned weight.
                    bonus = 4 if match.kind == "exact" else 2 * match.similarity
                    final[i] += bonus
                    if trace:
                        bonuses[i] = bonus
            candidates = sorted(candidates, key=lambda i: (-float(final[i]), -(self.docs[i].get("track_popularity") or 0) if popularity_ties else -float(fusion[i]), self.docs[i]["track_id"]))
        timings["reranking"] = (time.perf_counter() - stage_started) * 1000
        stage_started = time.perf_counter()
        results, related_results = [], []
        visible = candidates[:top_k]
        theme_supported = {i for i, evidence in theme_evidence.items() if plan.theme_profile != "moving_on" or evidence.get("topic_cues")}
        if automatic and query_type == "lyrics":
            direct = [i for i in candidates if i in lyric_matches][:top_k]
            similar = [i for i in candidates if i not in lyric_matches][:max(0, top_k - len(direct))]
            visible = direct + similar
        elif theme_evidence:
            direct = [i for i in candidates if i in theme_supported][:top_k]
            similar = [i for i in candidates if i not in theme_supported][:max(0, top_k - len(direct))]
            visible = direct + similar
        for i in visible:
            doc = self.docs[i]
            reasons = []
            if structured:
                reasons.append({"artist": "Anggota artis cocok dengan nama yang dicari", "title": "Judul cocok" if catalog_match["method"] == "exact" else "Judul mirip (toleransi satu kata)", "genre": "Label genre playlist cocok"}[query_type])
            if overlap(intent.text, doc["track_name"]) > 0:
                reasons.append("Kecocokan kata pada judul")
            if overlap(intent.text, doc["track_artist"]) > 0:
                reasons.append("Kecocokan kata pada artis")
            match = lyric_matches.get(i)
            if match:
                reasons.append("Potongan lirik cocok setelah normalisasi" if match.kind == "exact" else "Potongan lirik mirip (toleransi ejaan/kata)")
            elif phrase_match(intent.text, doc.get("lyrics", "")):
                reasons.append("Frasa query ditemukan dalam lirik")
            elif overlap(intent.text, doc.get("lyrics", "")) > 0:
                reasons.append("Kecocokan kata pada lirik")
            if use_semantic:
                reasons.append(f"Kemiripan makna: cosine {cosine[i]:.3f}")
            evidence = theme_evidence.get(i)
            if evidence:
                reasons.append(f"Bukti bagian lirik: cosine {evidence['cosine']:.3f}")
            if use_audio:
                for feature in sorted(set(intent.preferences) | {c[0] for c in intent.constraints}):
                    reasons.append(f"{feature}: {doc.get(feature)}")
            if not doc["lyrics_available"]:
                reasons.append("Lirik tidak tersedia")
            lines = [line.strip() for line in doc.get("lyrics", "").splitlines() if line.strip()]
            line = max(lines, key=lambda line: overlap(intent.text, line)) if lines else ""
            if match:
                line = match.snippet
            elif evidence:
                line = evidence["text"]
            is_related = automatic and query_type == "lyrics" and not match or bool(theme_evidence) and i not in theme_supported
            destination = related_results if is_related else results
            destination.append({**track_summary(doc), "score": float(final[i]), "snippet": line[:250],
                            "snippet_type": "semantic" if evidence else "lexical" if match or line and overlap(intent.text, line) > 0 else "preview",
                            **({"theme_evidence": evidence} if evidence else {}),
                            "lyric_match": {"kind": match.kind, "similarity": match.similarity} if match else None,
                            "reasons": reasons})
        eligibility_score = hard_audio_only or structured and catalog_match["method"] == "exact" and not intent.preferences
        ranking = {"score_kind": "eligibility" if eligibility_score else "audio_preference" if not intent.text and use_audio else "ranking",
                   "score_label": "Indikator memenuhi syarat" if eligibility_score else "Skor pemeringkatan",
                   "score_meaning": "Nilai 1 berarti seluruh syarat pencarian terpenuhi. Nilai ini tidak membedakan relevansi antarlagu dan bukan akurasi 100%." if eligibility_score else "Skor mengikuti kontribusi komponen pencarian; bukan probabilitas atau persentase akurasi.",
                   "order_by": ["score_desc", "popularity_desc" if popularity_ties else "rrf_desc", "track_id_asc"],
                   "order_label": "Kecocokan, lalu popularitas dataset; ID untuk nilai yang masih seri." if popularity_ties else "Skor, lalu RRF; ID untuk nilai yang masih seri."}
        if mode in {"E1", "E2"}:
            ranking.update(order_by=["bm25_desc", "track_id_asc"], order_label="BM25, lalu ID untuk nilai seri.")
        elif mode == "E3":
            ranking.update(order_by=["rrf_desc", "track_id_asc"], order_label="RRF, lalu ID untuk nilai seri.")
        response = {"query": query, "text_query": intent.text, "mode": mode, "backend": self.backend,
                "ranking": ranking,
                "mood": mood,
                "catalog_match": {k: v for k, v in catalog_match.items() if k != "track_ids"} if structured else None,
                "theme_profile": plan.theme_profile if plan else None,
                "query_type": query_type, "semantic_query": semantic_query if use_semantic else None,
                "pipeline": {"lexical": use_lexical, "semantic": use_semantic, "passage_reranking": bool(theme_evidence),
                             "audio": bool(use_audio), "reranking": rerank,
                             "degraded": automatic and needs_semantic and not use_semantic or passage_degraded},
                "warnings": warnings,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
                "candidate_ids": [self.docs[i]["track_id"] for i in candidates], "candidate_count": len(candidates),
                "constraints": intent.constraints, "preferences": intent.preferences, "results": results,
                "related_results": related_results,
                "result_policy": {"primary": "direct" if structured or query_type == "lyrics" else "supported" if theme_evidence else "ranked",
                                  "genre_source": "playlist_genre" if query_type == "genre" else None}}
        if trace:
            from .diagnostics import explain
            timings["formatting"] = (time.perf_counter() - stage_started) * 1000
            timings["wall_before_diagnostics"] = (time.perf_counter() - wall_started) * 1000
            response["trace"] = {
                "track_ids": [self.docs[i]["track_id"] for i in candidates],
                "features": [[float(f[i]) for f in features] for i in candidates] if features is not None else [],
                "audio": [float(audio[i]) for i in candidates],
                "rrf": [float(fusion[i]) for i in candidates],
                "has_text": bool(intent.text), "has_audio": intent.active,
            }
            response["trace"]["decisions"] = explain(self, response=response, rankings=dict(zip(source_names, lists)),
                retrieved=retrieved, before=before, bm=bm, cosine=cosine, mask=mask, audio=audio, fusion=fusion,
                features=features, weights=weights, text_score=text_score, audio_weight=weight, bonuses=bonuses,
                final=final, lyric_matches=lyric_matches, inspect_track_id=inspect_track_id,
                metadata_mask=metadata_mask, theme_evidence=theme_evidence, theme_mix=theme_mix, passage_stats=passage_stats,
                timings={key: round(value, 3) for key, value in timings.items()}, planned_kind=plan.kind if plan else query_type)
        return response
