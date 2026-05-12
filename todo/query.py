"""
Query parsing for mdone search.

Responsibilities
----------------
  normalize(text)
      Bidirectional text normalization applied to both the query and stored
      task fields before any comparison.  Removes intra-word hyphens, folds
      case, and strips extra whitespace.

  parse_query(raw) -> ParsedQuery
      Extracts structured filters and implicit field hints from a plain-text
      query string, leaving the unstructured remainder as `residual`.

  apply_filters(tasks, parsed, *, cli_tag, cli_priority) -> List[Task]
      Applies the hard filters from a ParsedQuery to a task list.
      CLI-level flag values take precedence over query-embedded ones.

Structured patterns (removed from residual_query)
--------------------------------------------------
  @<word>                     tag filter
  tag <word> / tagged <word>  tag filter
  in <section>                section filter
  section <section>           section filter
  due <date_expr>             due filter, resolved via dates.parse_due_date
  p<1-4>                      priority filter
  overdue                     semantic filter: due < today

Implicit hints (stay in residual; widen matching additively)
-------------------------------------------------------------
  <section_name>              maybe_sections hint
  high / urgent               maybe_priorities hint (1)
  medium                      maybe_priorities hint (2)
  low                         maybe_priorities hint (3)
  today / tomorrow            maybe_due hint
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date as _date
from typing import Dict, List, Optional

from .models import Task
from .storage import SECTIONS

# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def normalize(text: str) -> str:
    """Normalize *text* for search comparison.

    Steps
    -----
    1. NFKC unicode normalization (ligatures, full-width chars, etc.)
    2. Lowercase
    3. Remove hyphens **between letter characters only**
       (follow-up → followup, e-mail → email; 2026-05-15 is unchanged)
    4. Collapse whitespace runs to a single space, strip leading/trailing

    Examples
    --------
    >>> normalize("Follow-up")       == "followup"
    >>> normalize("E-mail Today")    == "email today"
    >>> normalize("2026-05-15")      == "2026-05-15"
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    # Only remove hyphens flanked by letter chars, not digit hyphens (dates)
    text = re.sub(r"(?<=[a-z])-(?=[a-z])", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Priority alias tables
# ---------------------------------------------------------------------------

# Explicit tokens: removed from residual, turned into a hard priority filter
PRIORITY_EXPLICIT: Dict[str, int] = {
    "p1": 1, "p2": 2, "p3": 3, "p4": 4,
}

# Implicit words: stay in residual for title matching, also add a hint
PRIORITY_IMPLICIT: Dict[str, int] = {
    "urgent": 1,
    "high":   1,
    "medium": 2,
    "low":    3,
}

_SECTION_SET = frozenset(SECTIONS)

# Common bare date words eligible for a maybe_due hint
_DATE_HINT_WORDS = frozenset({"today", "tomorrow", "yesterday"})


# ---------------------------------------------------------------------------
# ParsedQuery
# ---------------------------------------------------------------------------

@dataclass
class ParsedQuery:
    """Result of parse_query()."""

    raw: str                              # original, unmodified query
    residual: str                         # text left after extracting structured bits

    # Hard filters — tasks that don't pass are excluded before scoring
    filters: Dict[str, object] = field(default_factory=dict)

    # Additive hints — widen matching beyond title; do NOT exclude tasks
    hints: Dict[str, object] = field(default_factory=dict)

    def to_report(self) -> dict:
        """Return the JSON-facing subset (no internal implementation details)."""
        return {
            "resolved_filters": dict(self.filters),
            "residual_query": self.residual,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")


def _try_parse_date(text: str) -> Optional[str]:
    """Try to resolve *text* to an ISO date string; return None if unrecognised.

    Accepts the result if it matches the ISO pattern — whether or not it
    changed from the input (so already-ISO strings like "2099-06-01" pass).
    """
    from .dates import parse_due_date
    result = parse_due_date(text)
    if _ISO_RE.match(result):
        return result
    return None


# ---------------------------------------------------------------------------
# parse_query
# ---------------------------------------------------------------------------

def parse_query(raw: str) -> ParsedQuery:
    """Parse *raw* into structured filters and a residual text query.

    Extraction is greedy left-to-right. Unrecognised tokens remain in the
    residual query unchanged so they still participate in title matching.
    Parsing failures degrade gracefully — nothing is stripped unless a
    pattern is positively identified.
    """
    residual = raw.strip()
    filters: Dict[str, object] = {}
    hints: Dict[str, object] = {}

    # ------------------------------------------------------------------
    # 1. Explicit tag:  @word  |  tag word  |  tagged word
    # ------------------------------------------------------------------
    m = re.search(r"@(\w+)", residual)
    if m:
        filters["tag"] = m.group(1).lower()
        residual = (residual[: m.start()] + residual[m.end():]).strip()

    if "tag" not in filters:
        m = re.search(r"\b(?:tag|tagged)\s+(\w+)", residual, re.IGNORECASE)
        if m:
            filters["tag"] = m.group(1).lower()
            residual = (residual[: m.start()] + residual[m.end():]).strip()

    # ------------------------------------------------------------------
    # 2. Explicit section:  in <section>  |  section <section>
    # ------------------------------------------------------------------
    section_alt = "|".join(re.escape(s) for s in SECTIONS)
    m = re.search(
        rf"\b(?:in|section)\s+({section_alt})\b",
        residual,
        re.IGNORECASE,
    )
    if m:
        filters["section"] = m.group(1).lower()
        residual = (residual[: m.start()] + residual[m.end():]).strip()

    # ------------------------------------------------------------------
    # 3. Overdue  (before "due <date>" to avoid misparse)
    # ------------------------------------------------------------------
    m = re.search(r"\boverdue\b", residual, re.IGNORECASE)
    if m:
        filters["overdue"] = True
        residual = (residual[: m.start()] + residual[m.end():]).strip()

    # ------------------------------------------------------------------
    # 4. Explicit due date:  due <date_expr>
    #    Tries two-word phrase first, then single word.
    # ------------------------------------------------------------------
    if "due" not in filters:
        m = re.search(r"\bdue\s+(\S+)(?:\s+(\S+))?", residual, re.IGNORECASE)
        if m:
            resolved: Optional[str] = None
            span_end = m.end()   # default: consume both words

            if m.group(2):
                resolved = _try_parse_date(f"{m.group(1)} {m.group(2)}")

            if not resolved:
                resolved = _try_parse_date(m.group(1))
                if resolved:
                    # Only consume the one word following "due"
                    span_end = m.start(1) + len(m.group(1))

            if resolved:
                filters["due"] = resolved
                residual = (residual[: m.start()] + residual[span_end:]).strip()

    # ------------------------------------------------------------------
    # 5. Explicit priority:  p1 / p2 / p3 / p4
    # ------------------------------------------------------------------
    m = re.search(r"\bp([1-4])\b", residual, re.IGNORECASE)
    if m:
        filters["priority"] = int(m.group(1))
        residual = (residual[: m.start()] + residual[m.end():]).strip()

    # ------------------------------------------------------------------
    # Clean up residual whitespace
    # ------------------------------------------------------------------
    residual = re.sub(r"\s+", " ", residual).strip()

    # ------------------------------------------------------------------
    # 6. Implicit hints derived from residual tokens
    # ------------------------------------------------------------------
    residual_lower_toks = residual.lower().split()

    maybe_sections = [t for t in residual_lower_toks if t in _SECTION_SET]
    if maybe_sections and "section" not in filters:
        hints["maybe_sections"] = maybe_sections

    maybe_priorities = sorted({
        PRIORITY_IMPLICIT[t]
        for t in residual_lower_toks
        if t in PRIORITY_IMPLICIT and "priority" not in filters
    })
    if maybe_priorities:
        hints["maybe_priorities"] = maybe_priorities

    maybe_due: List[str] = []
    for tok in residual_lower_toks:
        if tok in _DATE_HINT_WORDS and "due" not in filters:
            resolved_date = _try_parse_date(tok)
            if resolved_date and resolved_date not in maybe_due:
                maybe_due.append(resolved_date)
    if maybe_due:
        hints["maybe_due"] = maybe_due

    return ParsedQuery(raw=raw, residual=residual, filters=filters, hints=hints)


# ---------------------------------------------------------------------------
# apply_filters
# ---------------------------------------------------------------------------

def apply_filters(
    tasks: List[Task],
    parsed: ParsedQuery,
    *,
    cli_tag: Optional[str] = None,
    cli_priority: Optional[int] = None,
) -> List[Task]:
    """Apply hard filters from *parsed* (and optional CLI overrides) to *tasks*.

    CLI-level values take precedence over query-embedded filters so that
    explicit flags are never silently overridden by query text.
    """
    f = parsed.filters
    today = _date.today().isoformat()

    tag      = cli_tag      if cli_tag      is not None else f.get("tag")
    priority = cli_priority if cli_priority is not None else f.get("priority")
    section  = f.get("section")
    due      = f.get("due")
    overdue  = f.get("overdue", False)

    result = tasks
    if tag:
        result = [t for t in result if tag in t.tags]
    if priority is not None:
        result = [t for t in result if t.priority == priority]
    if section:
        result = [t for t in result if t.section == section]
    if due:
        result = [t for t in result if t.due == due]
    if overdue:
        result = [t for t in result if t.due and t.due < today]

    return result
