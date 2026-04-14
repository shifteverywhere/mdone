"""
Phase 2 — date parsing, snooze helpers, and recurrence engine.

Due-date parsing (parse_due_date)
  Relative keywords : today, tomorrow, yesterday
  Named weekdays    : next-monday … next-sunday
  Relative intervals: in-N-days, in-N-weeks, in-N-months
  ISO 8601 passthrough: YYYY-MM-DD or YYYY-MM-DDTHH:MM

Snooze parsing (parse_snooze_duration)
  Duration shorthand: 30m | 2h | 1d  (relative to now)
  Absolute datetime : YYYY-MM-DDTHH:MM

Recurrence (next_recurrence, spawn_next_occurrence)
  Supported rules   : daily | weekly | monthly
"""

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Optional

from .models import Task
from .parser import generate_id


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday",
             "saturday", "sunday"]

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")
_DURATION_RE = re.compile(r"^(\d+)(m|h|d)$", re.IGNORECASE)
_INTERVAL_RE = re.compile(
    r"^in[- ](\d+)[- ](day|days|week|weeks|month|months)$", re.IGNORECASE
)


def _add_months(d: date, months: int) -> date:
    """Add months to a date, clamping to the last valid day of the result month."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


# ---------------------------------------------------------------------------
# Due-date parsing
# ---------------------------------------------------------------------------

def parse_due_date(value: str) -> str:
    """
    Normalise a due-date string to ISO 8601 (YYYY-MM-DD).
    Returns the original string unchanged if the format is unrecognised.

    Examples
    --------
    >>> parse_due_date("tomorrow")       # "2026-04-14"  (if today is Apr 13)
    >>> parse_due_date("next-friday")    # "2026-04-17"
    >>> parse_due_date("in-3-days")      # "2026-04-16"
    >>> parse_due_date("2026-04-15")     # "2026-04-15"  (passthrough)
    """
    v = value.strip()
    lower = v.lower()
    today = date.today()

    # Already ISO — return unchanged
    if _ISO_RE.match(v):
        return v

    # Plain keywords
    if lower == "today":
        return today.isoformat()
    if lower == "tomorrow":
        return (today + timedelta(days=1)).isoformat()
    if lower == "yesterday":
        return (today - timedelta(days=1)).isoformat()

    # next-<weekday>
    for i, day_name in enumerate(_WEEKDAYS):
        if lower in (f"next-{day_name}", f"next {day_name}"):
            days_ahead = i - today.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            return (today + timedelta(days=days_ahead)).isoformat()

    # in-N-<unit>
    m = _INTERVAL_RE.match(lower)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if "day" in unit:
            return (today + timedelta(days=n)).isoformat()
        if "week" in unit:
            return (today + timedelta(weeks=n)).isoformat()
        if "month" in unit:
            return _add_months(today, n).isoformat()

    return v  # unrecognised — pass through


# ---------------------------------------------------------------------------
# Snooze parsing
# ---------------------------------------------------------------------------

def parse_snooze_duration(value: str) -> str:
    """
    Parse a snooze argument into an absolute ISO-8601 datetime string
    (YYYY-MM-DDTHH:MM, seconds truncated).

    Accepts
    -------
    30m | 2h | 1d   — relative to *now*
    YYYY-MM-DDTHH:MM — absolute (validated and normalised)
    """
    v = value.strip()
    now = datetime.now().replace(second=0, microsecond=0)

    m = _DURATION_RE.match(v)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit == "m":
            result = now + timedelta(minutes=n)
        elif unit == "h":
            result = now + timedelta(hours=n)
        else:  # d
            result = now + timedelta(days=n)
        return result.strftime("%Y-%m-%dT%H:%M")

    # Try absolute ISO datetime
    try:
        dt = datetime.fromisoformat(v)
        return dt.strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        raise ValueError(f"Cannot parse snooze value: {v!r}. "
                         "Use 30m / 2h / 1d or YYYY-MM-DDTHH:MM.")


def is_snoozed(task: Task) -> bool:
    """Return True if the task's snooze datetime is still in the future."""
    if not task.snooze:
        return False
    try:
        return datetime.now() < datetime.fromisoformat(task.snooze)
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Recurrence engine
# ---------------------------------------------------------------------------

def next_recurrence(due: Optional[str], recur: str) -> Optional[str]:
    """
    Return the ISO date string for the next occurrence after task completion.

    Base date
    ---------
    Uses the task's due date (date part only).  Falls back to today if the
    due field is absent or unparseable.

    Supported rules
    ---------------
    daily   → base + 1 day
    weekly  → base + 7 days
    monthly → base + 1 calendar month (day clamped to month boundary)

    Returns None for unrecognised rules (RRULE support is Phase 4).
    """
    if due:
        try:
            base = date.fromisoformat(due.split("T")[0])
        except ValueError:
            base = date.today()
    else:
        base = date.today()

    lower = recur.strip().lower()
    if lower == "daily":
        return (base + timedelta(days=1)).isoformat()
    if lower == "weekly":
        return (base + timedelta(weeks=1)).isoformat()
    if lower == "monthly":
        return _add_months(base, 1).isoformat()

    return None  # RRULE / custom rules — Phase 4


def spawn_next_occurrence(task: Task) -> Optional[Task]:
    """
    Build the next occurrence of a recurring task with a fresh ID.
    Snooze is always cleared on the new occurrence.
    Returns None when the task has no recur rule or the rule is unrecognised.
    """
    if not task.recur:
        return None
    next_due = next_recurrence(task.due, task.recur)
    if next_due is None:
        return None
    return Task(
        title=task.title,
        id=generate_id(),
        done=False,
        tags=list(task.tags),
        contexts=list(task.contexts),
        due=next_due,
        recur=task.recur,
        priority=task.priority,
        notify=task.notify,
        snooze=None,
        section=task.section,
    )
