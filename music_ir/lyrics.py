"""Evidence from contiguous lyric windows, including bounded transcription errors.

No song-specific aliases or corrections. The original corpus is never rewritten.
"""
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from functools import lru_cache

from .data import normalize

WORDS = re.compile(r"[^\W_]+(?:['’‘ʼ][^\W_]+)*", re.UNICODE)
CONTRACTIONS = {
    "can't": ("can", "not"), "won't": ("will", "not"), "don't": ("do", "not"),
    "doesn't": ("does", "not"), "didn't": ("did", "not"), "isn't": ("is", "not"),
    "aren't": ("are", "not"), "wasn't": ("was", "not"), "weren't": ("were", "not"),
    "i'm": ("i", "am"), "you're": ("you", "are"), "we're": ("we", "are"),
    "they're": ("they", "are"), "it's": ("it", "is"), "that's": ("that", "is"),
    "he's": ("he", "is"), "she's": ("she", "is"), "there's": ("there", "is"),
}


def token_spans(text):
    for match in WORDS.finditer(text):
        word = unicodedata.normalize("NFKC", match.group()).casefold().translate(str.maketrans("’‘ʼ", "'''"))
        expanded = CONTRACTIONS.get(word)
        if expanded is None:
            for ending, expansion in (("'ll", "will"), ("'ve", "have")):
                if word.endswith(ending):
                    expanded = (word[:-len(ending)], expansion)
                    break
        for token in expanded or (word,):
            yield token, match.start(), match.end()


def lyric_tokens(text):
    return tuple(token for token, _, _ in token_spans(text))


@lru_cache(maxsize=8192)
def near_word(a, b):
    """One character insertion/deletion/substitution or adjacent transposition."""
    if min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        changed = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
        return len(changed) <= 1 or (len(changed) == 2 and changed[1] == changed[0] + 1
                                    and a[changed[0]] == b[changed[1]] and a[changed[1]] == b[changed[0]])
    short, long = (a, b) if len(a) < len(b) else (b, a)
    i = next((i for i, (x, y) in enumerate(zip(short, long)) if x != y), len(short))
    return short[i:] == long[i + 1:]


def token_distance(query, window):
    previous = list(range(len(window) + 1))
    for i, a in enumerate(query, 1):
        current = [i]
        for j, b in enumerate(window, 1):
            cost = 0 if a == b else .35 if near_word(a, b) else 1
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1]


@dataclass(frozen=True)
class LyricMatch:
    kind: str
    similarity: float
    snippet: str


class LyricIndex:
    def __init__(self, docs):
        self.docs = docs
        self.tokens = [lyric_tokens(doc.get("lyrics", "")) for doc in docs]
        self.postings = defaultdict(set)
        for i, words in enumerate(self.tokens):
            for word in set(words):
                self.postings[word].add(i)

    def evidence(self, i, start, end, kind, similarity):
        text = self.docs[i].get("lyrics", "")
        spans = list(token_spans(text))
        snippet = normalize(text[spans[start][1]:spans[end - 1][2]])[:250]
        return LyricMatch(kind, round(similarity, 4), snippet)

    def match(self, text):
        query = lyric_tokens(text)
        unique = set(query)
        if len(query) < 3 or len(unique) < 2:
            return {}
        matches = {}
        anchor = min(unique, key=lambda word: len(self.postings.get(word, ())))
        anchor_at = query.index(anchor)
        for i in self.postings.get(anchor, ()):
            words = self.tokens[i]
            for position, word in enumerate(words):
                start = position - anchor_at
                if word == anchor and start >= 0 and words[start:start + len(query)] == query:
                    matches[i] = self.evidence(i, start, start + len(query), "exact", 1.)
                    break
        if matches or len(query) < 4 or len(query) > 32 or len(unique) < 3:
            return matches

        # Fuzzy work is limited to tracks with substantial literal token support.
        support = Counter(i for word in unique for i in self.postings.get(word, ()))
        required = max(3, math.ceil(len(unique) * .6))
        candidates = sorted((i for i, count in support.items() if count >= required),
                            key=lambda i: (-support[i], self.docs[i]["track_id"]))[:200]
        allowance = 1 if len(query) <= 6 else 2
        for i in candidates:
            words = self.tokens[i]
            block = SequenceMatcher(None, query, words, autojunk=False).find_longest_match()
            expected = block.b - block.a
            best = None
            for start in range(max(0, expected - allowance), min(len(words), expected + allowance + 1)):
                for length in range(max(3, len(query) - allowance), len(query) + allowance + 1):
                    end = start + length
                    if end > len(words):
                        continue
                    window = words[start:end]
                    distance = token_distance(query, window)
                    similarity = 1 - distance / max(len(query), length)
                    if distance <= allowance and similarity >= .76:
                        if best is None or similarity > best[0]:
                            best = (similarity, start, end)
            if best is not None:
                matches[i] = self.evidence(i, best[1], best[2], "approximate", best[0])
        return matches
