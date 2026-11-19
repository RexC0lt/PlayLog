"""Pure title-matching helpers (no I/O) — unit tested directly."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_title(title: str | None) -> str:
    """Lowercase, strip accents/trademark symbols/punctuation, collapse whitespace."""
    if not title:
        return ""
    for symbol in ("™", "®", "©"):
        title = title.replace(symbol, " ")
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    text = _NON_ALNUM.sub(" ", text.lower())
    return " ".join(text.split())


def title_similarity(a: str | None, b: str | None) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def pick_best_igdb_match(title: str, candidates: list[dict], min_score: float = 0.6) -> dict | None:
    """Pick the best IGDB search candidate for a storefront title.

    Exact normalized matches win; otherwise the highest similarity above min_score.
    """
    if not candidates:
        return None
    norm = normalize_title(title)
    for candidate in candidates:
        if normalize_title(candidate.get("name")) == norm:
            return candidate
    best: dict | None = None
    best_score = 0.0
    for candidate in candidates:
        score = title_similarity(title, candidate.get("name"))
        if score > best_score:
            best, best_score = candidate, score
    if best is not None and best_score >= min_score:
        return best
    return None
