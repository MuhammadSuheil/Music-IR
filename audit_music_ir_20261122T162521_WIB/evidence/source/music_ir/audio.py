import re
from dataclasses import dataclass, field

import numpy as np

from .data import normalize, tokens

FEATURES = {"tempo": "tempo", "energy": "energy", "energi": "energy", "valence": "valence", "danceability": "danceability", "acousticness": "acousticness"}
OPERATORS = {">": ">", "<": "<", ">=": ">=", "<=": "<=", "=": "=", "di atas": ">", "di bawah": "<", "minimal": ">=", "maksimal": "<=", "setidaknya": ">=", "lebih dari": ">", "kurang dari": "<", "at least": ">=", "at most": "<=", "above": ">", "below": "<"}


@dataclass
class Intent:
    text: str
    constraints: list = field(default_factory=list)
    preferences: dict = field(default_factory=dict)

    @property
    def active(self):
        return bool(self.constraints or self.preferences)


def parse(query: str) -> Intent:
    query = normalize(query)
    if not tokens(query):
        raise ValueError("Query tidak boleh kosong.")
    names = "|".join(FEATURES)
    operators = "|".join(re.escape(k) for k in sorted(OPERATORS, key=len, reverse=True))
    pattern = rf"\b({names})\s*(tidak\s+)?({operators})\s*(\d+(?:[.,]\d+)?)\s*(?:bpm\b)?"
    intent = Intent(query)

    def numeric(match):
        feature, negation, operator, value = match.groups()
        feature, operator, value = FEATURES[feature.lower()], OPERATORS[operator.lower()], float(value.replace(",", "."))
        if negation:
            operator = {">": "<=", "<": ">=", ">=": "<", "<=": ">", "=": "!="}[operator]
        if value < 0 or (feature != "tempo" and value > 1):
            raise ValueError("Tempo memakai BPM nonnegatif; fitur lain memakai rentang 0–1.")
        intent.constraints.append((feature, operator, value))
        return " "

    text = re.sub(pattern, numeric, query, flags=re.IGNORECASE)
    soft = r"\b(tempo|energy|energi)\s+(tidak\s+)?(cepat|lambat|tinggi|rendah|fast|slow|high|low)\b"

    def preference(match):
        feature, negation, value = match.groups()
        feature = FEATURES[feature.lower()]
        high = value.lower() in {"cepat", "tinggi", "fast", "high"}
        if negation:
            high = not high
        if feature in intent.preferences and intent.preferences[feature] != high:
            raise ValueError(f"Preferensi {feature} saling bertentangan.")
        intent.preferences[feature] = high
        return " "

    text = re.sub(soft, preference, text, flags=re.IGNORECASE)
    if re.search(rf"\b({names})\s*(?:[<>!=]|di atas|di bawah|minimal|maksimal|tidak|[+-]?\d)", text, flags=re.IGNORECASE):
        raise ValueError("Batas audio belum dikenali. Contoh: tempo > 120 BPM, energi rendah.")
    if intent.active:
        text = re.sub(r"\b(lagu|musik|dengan|dan|yang|bertempo|bpm|bertema)\b", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"^[\s,;]+|[\s,;]+$", "", text)
    intent.text = normalize(text)
    return intent


def audio_scores(docs, intent):
    mask = np.ones(len(docs), dtype=bool)
    for feature, operator, bound in intent.constraints:
        values = np.array([d.get(feature) if d.get(feature) is not None else np.nan for d in docs], dtype=float)
        comparisons = {">": values > bound, "<": values < bound, ">=": values >= bound, "<=": values <= bound, "=": values == bound, "!=": values != bound}
        mask &= np.isfinite(values) & comparisons[operator]
    if not intent.active:
        return mask, np.zeros(len(docs))
    if not intent.preferences:
        return mask, np.ones(len(docs))
    parts = []
    for feature, high in intent.preferences.items():
        values = np.array([d.get(feature) if d.get(feature) is not None else np.nan for d in docs], dtype=float)
        valid = np.isfinite(values)
        population = np.sort(values[valid])
        scores = np.full(len(docs), .5)
        if len(population) > 1 and population[0] != population[-1]:
            # Mid-rank empirical percentile, including a deterministic tie policy.
            scores[valid] = (np.searchsorted(population, values[valid], side="left") + np.searchsorted(population, values[valid], side="right") - 1) / (2 * (len(population) - 1))
        parts.append(scores if high else 1 - scores)
    return mask, np.mean(parts, axis=0)
