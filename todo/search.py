"""
Full-text search over tasks with three scoring modes.

  similar  (default)  Jaccard similarity on title token sets + exact due match
  fuzzy               Token-level edit-distance on title + exact due match
  exact               Case-insensitive substring on title + exact due match

All modes return scores in the range 0.0–1.0.  Results whose score falls
below the mode-specific threshold are excluded.

Normalization
-------------
Both the query and stored field text are passed through query.normalize()
before any comparison.  This makes the following pairs match in all modes:

  followup  ↔  follow-up
  email     ↔  e-mail
  login     ↔  login          (fuzzy also handles "log in")

Fields searched
---------------
  title   — primary; scoring algorithm depends on mode
  due     — always exact substring match (ISO dates don't benefit from fuzzy)

Tag / section / priority hint matching is opt-in via the hints= parameter
and is added on top of title/due scoring by the caller (cmd_search).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from .models import Task
from .query import normalize, PRIORITY_IMPLICIT

# ---------------------------------------------------------------------------
# Mode registry
# ---------------------------------------------------------------------------

VALID_MODES = frozenset({"similar", "fuzzy", "exact"})

MODE_THRESHOLDS: Dict[str, float] = {
    "similar": 0.2,
    "fuzzy":   0.4,
    "exact":   0.01,
}


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    task: Task
    score: float                  # 0.0–1.0
    matched_fields: List[str]     # e.g. ["title", "tag", "section"]


# ---------------------------------------------------------------------------
# Utility functions (exported for tests and backward compat)
# ---------------------------------------------------------------------------

def _tokens(text: str) -> List[str]:
    """Split *text* into normalized lowercase tokens."""
    return [t for t in re.split(r"[\s,]+", normalize(text)) if t]


def _field_score(value: str, tokens: List[str]) -> int:
    """Return the count of tokens that appear as substrings in *value*."""
    lower = normalize(value)
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
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + (0 if ca == cb else 1),
            ))
        prev = curr
    return prev[-1]


# ---------------------------------------------------------------------------
# Title scorers — operate on pre-normalized strings
# ---------------------------------------------------------------------------

def _score_title_exact(query: str, title: str) -> float:
    """1.0 if *query* is a substring of *title*, else 0.0. (Both pre-normalized.)"""
    return 1.0 if query in title else 0.0


def _score_title_fuzzy(query: str, title: str) -> float:
    """Average best-match edit-distance similarity across query tokens.

    For each query token the closest title token is found by Levenshtein
    distance and converted to a 0–1 similarity score.  The per-token scores
    are averaged to produce the final result.
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
# Due scorer — always exact substring, regardless of mode
# ---------------------------------------------------------------------------

def _score_due(query_norm: str, due: Optional[str]) -> float:
    """1.0 if *query_norm* is a substring of *due* (normalized), else 0.0."""
    if not due:
        return 0.0
    return 1.0 if query_norm in normalize(due) else 0.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def search_tasks(
    query: str,
    tasks: List[Task],
    mode: str = "similar",
    threshold: Optional[float] = None,
    hints: Optional[Dict] = None,
) -> List[SearchResult]:
    """Score and rank *tasks* against *query*.

    Parameters
    ----------
    query      Free-text query string.
    tasks      Candidate task list (already hard-filtered by apply_filters).
    mode       "similar" | "fuzzy" | "exact"  (default "similar").
    threshold  Minimum score; if None uses MODE_THRESHOLDS[mode].
    hints      Additive field hints from parse_query().  When not None,
               hint matching is enabled:

               - Any query token that matches a task tag → "tag" in matched_fields
               - hints["maybe_sections"]  → "section" in matched_fields
               - hints["maybe_priorities"]→ "priority" in matched_fields
               - hints["maybe_due"]       → "due" in matched_fields (additive)

               Hint-only matches (no title/due score) are included at 0.7.
               When hints=None (the default), only title/due are scored.

    Returns
    -------
    List of SearchResult sorted highest score first; scores below threshold
    are excluded.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of: {', '.join(sorted(VALID_MODES))}")
    if not query:
        return []
    if threshold is None:
        threshold = MODE_THRESHOLDS[mode]

    q_norm = normalize(query)
    q_toks: Set[str] = set(_tokens(q_norm))   # used for tag matching

    title_scorer = _TITLE_SCORERS[mode]
    results: List[SearchResult] = []

    for task in tasks:
        # ---- title + due scoring (always) ----
        t_norm = normalize(task.title)
        title_score = title_scorer(q_norm, t_norm)
        due_score   = _score_due(q_norm, task.due)

        matched: List[str] = []
        if title_score >= threshold:
            matched.append("title")
        if due_score > 0.0:
            matched.append("due")

        # ---- additive hint matching (only when hints is not None) ----
        extra: List[str] = []
        if hints is not None:
            # Tag: any query token matches any task tag (normalized)
            if q_toks:
                task_tags_norm = {normalize(tg) for tg in task.tags}
                if q_toks & task_tags_norm:
                    extra.append("tag")

            # Section hint
            if "maybe_sections" in hints and task.section in hints["maybe_sections"]:
                extra.append("section")

            # Priority hint
            if "maybe_priorities" in hints and task.priority in hints["maybe_priorities"]:
                extra.append("priority")

            # Due hint (additive — task.due matches a bare date phrase in query)
            if "maybe_due" in hints:
                if task.due and task.due in hints["maybe_due"] and "due" not in matched:
                    extra.append("due")

        all_matched = matched + [f for f in extra if f not in matched]

        if not all_matched:
            continue

        # ---- final score ----
        n_extra = len(extra)
        if "title" in matched:
            # Title is the primary driver; small additive boost per hint match
            final = min(1.0, title_score + 0.03 * n_extra)
            if "due" in matched:
                final = min(1.0, final + 0.05)
        elif "due" in matched:
            final = 0.9  # exact date match, no title overlap
        else:
            # Hint-only match (tag / section / priority)
            final = 0.7

        results.append(SearchResult(
            task=task,
            score=round(final, 3),
            matched_fields=all_matched,
        ))

    results.sort(key=lambda r: (-r.score, r.task.title.lower()))
    return results
