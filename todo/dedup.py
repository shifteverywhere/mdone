"""
Deduplication helpers.

Exact match:  find_by_idempotency_key() — O(n) scan on idempotency_key field
Fuzzy match:  similar_tasks() — Jaccard similarity on title token sets
"""

import re
from typing import List, Optional, Tuple

from .models import Task

# Jaccard threshold above which a task is considered a duplicate when --dedup is used.
DEDUP_THRESHOLD = 0.5

_STOP_WORDS = {
    "a", "an", "the", "to", "in", "on", "at", "for", "of", "and", "or",
    "is", "it", "be", "do", "my", "me", "we", "us", "as", "by", "get",
}


def _tokens(title: str) -> frozenset:
    words = re.findall(r"\w+", title.lower())
    return frozenset(w for w in words if len(w) >= 3 and w not in _STOP_WORDS)


def _jaccard(a: frozenset, b: frozenset) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def find_by_idempotency_key(key: str, tasks: List[Task]) -> Optional[Task]:
    """Return the first task whose idempotency_key matches key, or None."""
    for task in tasks:
        if task.idempotency_key == key:
            return task
    return None


def similar_tasks(
    title: str,
    tasks: List[Task],
    threshold: float = 0.0,
) -> List[Tuple[float, Task]]:
    """Return (score, task) pairs with Jaccard score >= threshold, sorted descending.

    A score of 1.0 means the title token sets are identical.
    Tasks with empty token sets (very short titles) are skipped.
    """
    query = _tokens(title)
    if not query:
        return []

    results = []
    for task in tasks:
        candidate = _tokens(task.title)
        if not candidate:
            continue
        score = _jaccard(query, candidate)
        if score >= threshold:
            results.append((score, task))

    results.sort(key=lambda x: (-x[0], x[1].title.lower()))
    return results
