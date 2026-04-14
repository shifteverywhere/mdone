"""
Full-text search over tasks.md (and optionally archive.md).

search_tasks(query, tasks) applies a ranked, case-insensitive match against:
  - title (weight 3)
  - tags  (weight 2)
  - contexts, due, recur (weight 1)

Each match returns a SearchResult with the task and a numeric score.
Results are sorted highest-score first; zero-score tasks are excluded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from .models import Task


@dataclass
class SearchResult:
    task: Task
    score: int
    matched_fields: List[str]   # human-readable list of which fields matched


def _tokens(query: str) -> List[str]:
    """Split query into lowercase tokens, ignoring empty strings."""
    return [t.lower() for t in re.split(r"[\s,]+", query) if t]


def _field_score(value: str, tokens: List[str]) -> int:
    """Return the number of tokens that appear in value (case-insensitive)."""
    lower = value.lower()
    return sum(1 for tok in tokens if tok in lower)


def search_tasks(query: str, tasks: List[Task]) -> List[SearchResult]:
    """
    Score and filter tasks against *query*.

    Weights
    -------
    title    ×3
    tags     ×2 (each tag is scored independently, any hit counts)
    due      ×1
    recur    ×1
    contexts ×1
    """
    tokens = _tokens(query)
    if not tokens:
        return []

    results = []
    for task in tasks:
        score = 0
        matched: List[str] = []

        # title
        s = _field_score(task.title, tokens) * 3
        if s:
            score += s
            matched.append("title")

        # tags
        tag_str = " ".join(task.tags)
        s = _field_score(tag_str, tokens) * 2
        if s:
            score += s
            matched.append("tags")

        # contexts
        ctx_str = " ".join(task.contexts)
        s = _field_score(ctx_str, tokens)
        if s:
            score += s
            matched.append("contexts")

        # due
        if task.due:
            s = _field_score(task.due, tokens)
            if s:
                score += s
                matched.append("due")

        # recur
        if task.recur:
            s = _field_score(task.recur, tokens)
            if s:
                score += s
                matched.append("recur")

        if score > 0:
            results.append(SearchResult(task=task, score=score, matched_fields=matched))

    results.sort(key=lambda r: (-r.score, r.task.title.lower()))
    return results
