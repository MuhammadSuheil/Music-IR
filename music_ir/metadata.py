"""Catalog intent detection. All matches are derived from the current corpus."""
import re
from collections import defaultdict
from difflib import SequenceMatcher

from .data import normalize, tokens


def key(text):
    return " ".join(tokens(text))


class MetadataIndex:
    def __init__(self, docs):
        self.titles, self.artists, self.genres = (defaultdict(set) for _ in range(3))
        self.genre_names = {}
        for doc in docs:
            track_id = doc["track_id"]
            self.titles[key(doc["track_name"])].add(track_id)
            # Contiguous credit spans also cover names containing a comma,
            # e.g. 'Tyler, The Creator' inside a longer collaboration credit.
            credits = doc["track_artist"].split(",")
            for artist in [",".join(credits[start:end]) for start in range(len(credits)) for end in range(start + 1, len(credits) + 1)]:
                if key(artist):
                    self.artists[key(artist)].add(track_id)
            for genre in doc.get("playlist_genre", []):
                self.genres[key(genre)].add(track_id)
                self.genre_names[key(genre)] = genre

    def match(self, text, allow_fuzzy=True):
        normalized = key(text)
        for kind, index in [("title", self.titles), ("artist", self.artists)]:
            if normalized in index:
                return self.result(kind, text, index[normalized])
        artist = re.fullmatch(r"(?:(?:lagu|musik)\s+(?:dari|oleh)|artis|artist|(?:songs?|music)\s+by)\s+(.+)", text, re.I)
        if artist:
            return self.result("artist", artist[1], self.artists.get(key(artist[1]), ()))
        title = re.fullmatch(r"(?:judul|lagu\s+berjudul|song\s+titled)\s+(.+)", text, re.I)
        focus = key(title[1].strip('"')) if title else normalized
        if title and focus in self.titles:
            return self.result("title", title[1], self.titles[focus])
        genre = re.fullmatch(r"(?:(?:lagu|musik|songs?|music)(?:\s+(?:bergenre|genre))?\s+(.+)|(.+?)\s+(?:songs?|music)|genre\s+(.+))", text, re.I)
        genre_key = key(next((part for part in genre.groups() if part), "")) if genre else normalized
        if genre_key in self.genres:
            return self.result("genre", self.genre_names[genre_key], self.genres[genre_key])
        if re.match(r"^(?:genre|(?:lagu|musik)\s+bergenre)\s+", text, re.I):
            return self.result("genre", next((part for part in genre.groups() if part), text) if genre else text, ())
        # One substituted/omitted word in a multiword title; never rewrite lyrics.
        words = focus.split()
        matches = {}
        if allow_fuzzy and len(words) >= 3:
            for name, ids in self.titles.items():
                other = name.split()
                alignment = SequenceMatcher(None, words, other, autojunk=False)
                ratio = alignment.ratio()
                edits = sum(max(right - left, end - start) for tag, left, right, start, end in alignment.get_opcodes() if tag != "equal")
                common = len(set(words) & set(other))
                if ratio >= .75 and common >= 3 and edits <= 1:
                    matches.update({track_id: ratio for track_id in ids})
        if matches:
            best = max(matches.values())
            selected = {track_id for track_id, score in matches.items() if score == best}
            return self.result("title", title[1] if title else text, selected, "approximate", best)
        return None

    @staticmethod
    def result(kind, value, ids, method="exact", similarity=1.):
        return {"kind": kind, "value": normalize(value), "track_ids": tuple(sorted(ids)),
                "method": method, "similarity": similarity,
                **({"source": "playlist_genre"} if kind == "genre" else {})}
