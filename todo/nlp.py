"""
Phase 3 — Natural language parsing and tag inference.

parse_natural(text) → dict(title, due, priority, tags)

dateparser is an optional dependency.  When it is absent, date extraction is
skipped and the cleaned text is used as the title as-is.  All other features
(priority inference, tag inference, filler stripping) work without it.
"""

import re
from typing import List, Optional

# ---------------------------------------------------------------------------
# Optional dateparser import
# ---------------------------------------------------------------------------

try:
    from dateparser.search import search_dates as _search_dates  # type: ignore
    _DATEPARSER_AVAILABLE = True
except ImportError:
    _search_dates = None          # type: ignore
    _DATEPARSER_AVAILABLE = False


# ---------------------------------------------------------------------------
# Priority inference
# ---------------------------------------------------------------------------

_PRIORITY_PATTERNS = [
    (1, ["urgent", "asap", "critical", "immediately", "emergency", "right away"]),
    (2, ["important", "high priority", "high-priority"]),
    (3, ["medium", "moderate", "normal priority"]),
    (4, ["low priority", "low-priority", "someday", "eventually",
         "when possible", "nice to have", "nice-to-have", "if time"]),
]


def infer_priority(text: str) -> int:
    """
    Return the inferred priority (1–4) from natural-language text.
    Scans patterns in priority order; first match wins.  Default is 4.
    """
    lower = text.lower()
    for priority, phrases in _PRIORITY_PATTERNS:
        if any(phrase in lower for phrase in phrases):
            return priority
    return 4


# ---------------------------------------------------------------------------
# Tag inference
# ---------------------------------------------------------------------------

_TAG_KEYWORDS: dict = {
    "health":   ["doctor", "dentist", "gym", "medicine", "pharmacy",
                 "hospital", "appointment", "workout", "exercise",
                 "physio", "prescription", "therapist", "checkup"],
    "work":     ["meeting", "pull request", "review", "bug", "deploy",
                 "ticket", "sprint", "standup", "stand-up", "client",
                 "presentation", "deadline", "report", "proposal",
                 "interview", "conference", "onboarding"],
    "shopping": ["buy", "purchase", "groceries", "grocery", "store",
                 "order", "pick up", "supermarket", "amazon"],
    "finance":  ["pay", "bill", "invoice", "expense", "tax", "bank",
                 "transfer", "subscription", "renew", "payment", "receipt"],
    "home":     ["clean", "fix", "repair", "laundry", "dishes", "vacuum",
                 "tidy", "organise", "organize", "declutter",
                 "plumber", "electrician"],
    "personal": ["birthday", "anniversary", "gift", "friend", "family",
                 "wedding", "party", "social"],
}


def infer_tags(text: str) -> List[str]:
    """
    Return tag names inferred from keyword matching.
    The @ prefix is NOT included in the returned strings.
    """
    padded = f" {text.lower()} "   # pad so substring matching behaves correctly
    return [tag for tag, kws in _TAG_KEYWORDS.items() if any(kw in padded for kw in kws)]


# ---------------------------------------------------------------------------
# Title-cleaning helpers
# ---------------------------------------------------------------------------

# Filler phrases stripped from the very start of the input
_FILLER_RES = [
    re.compile(r"^remind\s+me\s+to\s+", re.I),
    re.compile(r"^don['\u2019]?t\s+forget\s+to\s+", re.I),
    re.compile(r"^i\s+need\s+to\s+", re.I),
    re.compile(r"^i\s+have\s+to\s+", re.I),
    re.compile(r"^i\s+should\s+", re.I),
    re.compile(r"^make\s+sure\s+to\s+", re.I),
    re.compile(r"^remember\s+to\s+", re.I),
    re.compile(r"^please\s+", re.I),
    re.compile(r"^can\s+you\s+", re.I),
    re.compile(r"^(?:add\s+)?(?:a\s+)?(?:task\s+)?to\s+", re.I),
    re.compile(r"^schedule\s+(?:a\s+)?(?:time\s+)?(?:to\s+)?", re.I),
]

# Priority words at the very start of a title ("Urgent: fix the bug …")
_PRIORITY_PREFIX_RE = re.compile(
    r"^(?:urgent|important|asap|critical|high[\s\-]priority|low[\s\-]priority|someday)"
    r"[\s:\-]+",
    re.I,
)

# Trailing prepositions left dangling after the date phrase is removed
_TRAILING_PREP_RE = re.compile(
    r"\s+(?:on|at|by|before|after|for|this|next|coming|the)\s*$", re.I
)

# Leading prepositions left after the date phrase is removed from the front
_LEADING_PREP_RE = re.compile(r"^(?:on|at|by|before|after|for)\s+", re.I)


def _strip_fillers(text: str) -> str:
    for pat in _FILLER_RES:
        text = pat.sub("", text)
    return text.strip()


def _clean_title(text: str) -> str:
    text = _TRAILING_PREP_RE.sub("", text)
    text = _LEADING_PREP_RE.sub("", text)
    text = _PRIORITY_PREFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text:
        text = text[0].upper() + text[1:]
    return text


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def parse_natural(text: str) -> dict:
    """
    Parse a natural-language task description into structured fields.

    Parameters
    ----------
    text : str
        Free-form English, e.g. "remind me to call Alice next Friday at 3pm"

    Returns
    -------
    dict with keys:
        title    : str         — cleaned title
        due      : str | None  — ISO 8601 date or datetime string
        priority : int         — 1–4, inferred from priority signal words
        tags     : list[str]   — inferred tag names (without @)

    Notes
    -----
    * Priority and tag inference always run on the *original* text so that
      signal words removed during title cleanup are still detected.
    * Date extraction runs on the filler-stripped text.  When dateparser is
      not installed, ``due`` is always ``None``.
    """
    remaining = _strip_fillers(text)
    due_str: Optional[str] = None

    if _DATEPARSER_AVAILABLE and _search_dates is not None:
        results = _search_dates(
            remaining,
            settings={
                "PREFER_DATES_FROM": "future",
                "RETURN_AS_TIMEZONE_AWARE": False,
            },
        ) or []

        if results:
            date_phrase, parsed_dt = results[0]
            # Include time only when it is explicitly non-midnight
            if parsed_dt.hour == 0 and parsed_dt.minute == 0:
                due_str = parsed_dt.strftime("%Y-%m-%d")
            else:
                due_str = parsed_dt.strftime("%Y-%m-%dT%H:%M")
            # Remove the matched phrase from the remaining text
            remaining = remaining.replace(date_phrase, "", 1)

    title = _clean_title(remaining)
    priority = infer_priority(text)   # scan original text — catches "urgent: …"
    tags = infer_tags(title)          # infer from cleaned title

    return {
        "title":    title,
        "due":      due_str,
        "priority": priority,
        "tags":     tags,
    }
