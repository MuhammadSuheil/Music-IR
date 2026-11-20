"""Small, inspectable query rules for AUTO; experiment queries stay unchanged."""
import re
from dataclasses import dataclass

from .data import normalize, tokens


@dataclass(frozen=True)
class QueryPlan:
    text: str
    kind: str = "text"
    semantic_text: str = ""
    audio_text: str = ""
    mood: str | None = None
    catalog_match: dict | None = None
    theme_profile: str | None = None


MOODS = {
    "happy": ("happy", "happiness, joy, feeling happy and celebrating life"),
    "bahagia": ("happy", "happiness, joy, feeling happy and celebrating life"),
    "ceria": ("happy", "happiness, joy, feeling cheerful and celebrating life"),
    "gembira": ("happy", "happiness, joy, feeling happy and celebrating life"),
    "sad": ("sad", "sadness, sorrow, heartbreak and feeling sad"),
    "sadness": ("sad", "sadness, sorrow, heartbreak and feeling sad"),
    "sedih": ("sad", "sadness, sorrow, heartbreak and feeling sad"),
    "kesedihan": ("sad", "sadness, sorrow, heartbreak and feeling sad"),
    "sendu": ("sad", "sadness, sorrow, heartbreak and feeling sad"),
    "galau": ("sad", "heartbreak, longing and uncertainty in a relationship"),
}


def theme_plan(focus):
    focus = normalize(focus)
    mood = MOODS.get(focus.casefold())
    if mood:
        return QueryPlan(focus, "semantic", mood[1], mood=mood[0])
    if focus.casefold() in {"cinta", "love", "kasih sayang", "cinta romantis", "romantic love"}:
        return QueryPlan(focus, "semantic", focus + ". Lyrics about romantic love, affection, devotion and a relationship between partners.", theme_profile="romance")
    if re.search(r"\b(?:sulit|susah|belum bisa|tidak bisa|tak bisa)\b.*\b(?:melupakan|lupa|move on)\b", focus, re.I):
        return QueryPlan(focus, "semantic", focus + ". Lyrics about being unable to move on after a breakup, missing a former lover and lingering heartbreak.", theme_profile="moving_on")
    return QueryPlan(focus, "semantic", focus)


def plan_query(text, original="", metadata_names=(), metadata=None):
    text = normalize(text)
    lyric_prefix = re.compile(
        r"^(?:(?:cari(?:kan)?|find)\s+)?(?:lagu\s+(?:yang\s+)?(?:liriknya|berlirik)|potongan\s+lirik|lirik(?:nya)?|lyrics?)\s*[:\-]?\s+(.+)$",
        re.IGNORECASE,
    )
    explicit = lyric_prefix.match(text)
    quoted = re.search(r'["“]([^"”]+)["”]', text)
    if explicit or quoted and not re.match(r"^(?:judul|lagu\s+berjudul|song\s+titled)\b", text, re.I):
        literal = quoted.group(1) if quoted else explicit.group(1).strip('"“”')
        if not tokens(literal):
            raise ValueError("Potongan lirik tidak boleh kosong.")
        outer = normalize(text[:quoted.start()] + " " + text[quoted.end():]) if quoted else ""
        return QueryPlan(normalize(literal), "lyrics", normalize(literal), outer)

    theme_prefix = re.match(r"^(?:cari(?:kan)?\s+)?(?:lagu|musik|(?:a\s+)?songs?|music)\s+(?:yang\s+)?(?:tentang|bertema|bermakna|mengenai|about|dengan\s+makna)\s+", text, re.I)
    catalog_match = metadata.match(text, allow_fuzzy=not theme_prefix) if metadata is not None else None
    if catalog_match:
        return QueryPlan(catalog_match["value"], catalog_match["kind"], catalog_match=catalog_match)
    if text.casefold() in metadata_names:
        return QueryPlan(text, semantic_text=text)

    # Audio parsing may have removed the initial word 'lagu'.
    wrapped = text
    if re.match(r"^(?:lagu|musik)\b", normalize(original), re.IGNORECASE) and not re.match(r"^(?:lagu|musik)\b", text, re.IGNORECASE):
        wrapped = "lagu " + text
    theme = re.match(r"^(?:cari(?:kan)?\s+)?(?:(?:lagu|musik)|(?:a\s+)?(?:songs?|music))\s+(?:yang\s+)?(?:tentang|bertema|bermakna|mengenai|about|dengan\s+makna)\s+(.+)$", wrapped, re.IGNORECASE)
    if theme:
        return theme_plan(theme.group(1))
    mood = re.fullmatch(r"(?:lagu|musik|songs?|music)\s+(?:yang\s+)?(" + "|".join(MOODS) + r")", wrapped, re.IGNORECASE)
    if mood:
        return theme_plan(mood.group(1).casefold())
    # Audio parsing can remove the word 'lagu'; retain a clearly requested mood.
    if text.casefold() in MOODS and re.match(r"^(?:lagu|musik)\b", normalize(original), re.IGNORECASE):
        return theme_plan(text)
    return QueryPlan(text, semantic_text=text)
