"""
Full-text search over tasks with three scoring modes.

  similar  (default)  Jaccard similarity on title token sets + exact due match
  fuzzy               Token-level edit-distance on title + exact due match
  exact               Case-insensitive substring on title + exact due match

All modes return scores in the range 0.0–1.0.  Results whose score falls
below the mode-specific threshold are excluded.

Fields searched
---------------
  title   — primary; scoring algorithm depends on mode
  due     — always exact substring match (date strings don't benefit from fuzzy)

Only these two fields are reported in matched_fields.  Tag / context / recur
filters are applied at the CLI level before calling search_tasks().
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .models import Task

# ---------------------------------------------------------------------------
# Mode registry
# ---------------------------------------------------------------------------

VALID_MODES = frozenset({"similar", "fuzzy", "exact"})

# Minimum score required for a result to be included.
MODE_THRESHOLDS: dict[str, float] = {
    "similar": 0.2,   # at least 20 % token overlap
    "fuzzy":   0.4,   # at least 40 % character similarity on closest word pair
    "exact":   0.01,  # any substring match
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    task: Task
    score: float           # 0.0–1.0
    matched_fields: List[str]   # subset of {"title", "due"}


# ---------------------------------------------------------------------------
# Private utilities (kept for test imports and internal use)
# ---------------------------------------------------------------------------

def _tokens(text: str) -> List[str]:
    """Split text into lowercase tokens, ignoring empty strings."""
    return [t.lower() for t in re.split(r"[\s,]+", text) if t]


def _field_score(value: str, tokens: List[str]) -> int:
    """Return the count of tokens that appear as substrings in value."""
    lower = value.lower()
    return sum(1 for tok in tokens if tok in lower)


def _levenshtein(a: str, b: str) -> int:
    """Standard dynamic-programming Levenshtein edit distance."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            curr.append(min(
                prev[j] + 1,        # deletion
                curr[j - 1] + 1,    # insertion
                prev[j - 1] + (0 if ca == cb else 1),  # substitution
            ))
        prev = curr
    return prev[-1]


# ---------------------------------------------------------------------------
# Title scorers (one per mode)
# ---------------------------------------------------------------------------

def _score_title_exact(query: str, title: str) -> float:
    """1.0 if query is a case-insensitive substring of title, else 0.0."""
    return 1.0 if query.lower() in title.lower() else 0.0


def _score_title_fuzzy(query: str, title: str) -> float:
    """Average best-match edit-distance similarity across query tokens.

    For each query token we find the title token that requires the fewest
    edits, compute a 0–1 similarity, and average over all query tokens.
    This lets "meeitng" match "meeting" with high confidence.
    """
    q_toks = _tokens(query)
    t_toks = _tokens(title)
    if not q_toks or not t_toks:
        return 0.0
    total = 0.0
    for qt in q_toks:
        best = max(
            1.0 - _levenshtein(qt, tt) / max(len(qt), len(tt))
            for tt in t_toks
        )
        total += best
    return total / len(q_toks)


def _score_title_similar(query: str, title: str) -> float:
    """Jaccard similarity between the query token set and the title token set."""
    q_set = set(_tokens(query))
    t_set = set(_tokens(title))
    if not q_set or not t_set:
        return 0.0
    return len(q_set & t_set) / len(q_set | t_set)


_TITLE_SCORERS = {
    "exact":   _score_title_exact,
    "fuzzy":   _score_title_fuzzy,
    "similar": _score_title_similar,
}

# ---------------------------------------------------------------------------
# Due-date scorer (always exact substring, regardless of mode)
# ---------------------------------------------------------------------------

def _score_due(query: str, due: Optional[str]) -> float:
    """1.0 if query is a case-insensitive substring of the due string, else 0.0."""
    if not due:
        return 0.0
    return 1.0 if query.lower() in due.lower() else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_tasks(
    query: str,
    tasks: List[Task],
    mode: str = "similar",
    threshold: Optional[float] = None,
) -> List[SearchResult]:
    """Score and rank *tasks* against *query*.

    Parameters
    ----------
    query      Free-text query string.
    tasks      Candidate task list (pre-filtered by tag / priority etc.).
    mode       Scoring mode: "similar" | "fuzzy" | "exact"  (default "similar").
    threshold  Minimum score to include.  If None, uses MODE_THRESHOLDS[mode].

    Returns
    -------
    List of SearchResult, sorted highest score first.  Results with a score
    below the effective threshold are excluded.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_MODES))}")
    if not query:
        return []
    if threshold is None:
        threshold = MODE_THRESHOLDS[mode]

    title_scorer = _TITLE_SCORERS[mode]
    results: List[SearchResult] = []

    for task in tasks:
        matched: List[str] = []

        title_score = title_scorer(query, task.title)
        due_score = _score_due(query, task.due)

        if title_score >= threshold:
            matched.append("title")
        if due_score > 0.0:   # due is always binary; any match counts
            matched.append("due")

        if not matched:
            continue

        # Final score: title drives ranking; due-only matches get a fixed 0.9
        # (high-confidence exact date match).  Both matching gets a small boost.
        if "title" in matched and "due" in matched:
            final = min(1.0, title_score + 0.05)
        elif "title" in matched:
            final = title_score
        else:
            final = 0.9  # due-only exact match

        results.append(SearchResult(
            task=task,
            score=round(final, 3),
            matched_fields=matched,
        ))

    results.sort(key=lambda r: (-r.score, r.task.title.lower()))
    return results
