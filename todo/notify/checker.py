"""
Notification checker — determines which tasks are pending notification
and manages the .notified deduplication state file.

.notified key format
--------------------
Each entry is:    task_id:offset  TAB  iso_datetime

Where *offset* is the notify lead-time string that triggered this entry
(e.g. "30m", "2h", "1d") or the special sentinel "overdue".

Legacy entries (bare task_id with no colon) are treated as a wildcard:
they suppress ALL offset notifications for that task, preserving
backward-compatibility with older .notified files.

Multiple offsets
----------------
A task may have notify:"30m,2h,1d" (comma-separated).  Each offset is
tracked and fired independently.  An offset fires when:

  now >= due - lead_time   AND   task_id:offset NOT in .notified

Additionally, when a task becomes overdue the "overdue" sentinel fires
exactly once (task_id:overdue), regardless of the notify field.

Quiet hours
-----------
If config["notifications"]["quiet_hours"] is set (e.g. "22:00-08:00"),
build_pending() returns an empty list during that window.  The next poll
after the window ends will fire all accumulated notifications.
Cross-midnight ranges are supported.

Snooze re-arm
-------------
Snoozing a task (via cmd_snooze) calls reset_notified(task_id), which
clears all .notified entries for that task.  After the snooze expires the
task becomes visible again and notification fires normally.
"""

from __future__ import annotations

import re
from datetime import datetime, time as _time, timedelta
from pathlib import Path
from typing import List, Optional

from ..models import Task
from ..dates import is_snoozed
from ..storage import get_todo_dir, read_tasks

# ---------------------------------------------------------------------------
# .notified file helpers
# ---------------------------------------------------------------------------

def _notified_file() -> Path:
    return get_todo_dir() / ".notified"


def load_notified() -> dict:
    """Return {key: iso_datetime_string} for all entries in .notified.

    Keys are either composite (task_id:offset) for new entries or bare
    task_ids for legacy entries written by older versions.
    """
    f = _notified_file()
    if not f.exists():
        return {}
    result = {}
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 1)
        if len(parts) == 2:
            result[parts[0]] = parts[1]
    return result


def mark_sent(keys: List[str]) -> None:
    """Append *keys* to .notified with the current timestamp.

    Keys should be composite strings of the form ``task_id:offset``
    (e.g. ``abc123:30m``, ``abc123:overdue``).  Bare task IDs are
    accepted for backward compatibility but won't suppress per-offset
    checks in build_pending.
    """
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")
    with _notified_file().open("a") as f:
        for key in keys:
            f.write(f"{key}\t{now_str}\n")


def reset_notified(task_id: Optional[str] = None) -> None:
    """Clear .notified entirely, or remove all entries for *task_id*.

    Removes both new-format (task_id:offset) and legacy (bare task_id)
    entries for the given task.
    """
    f = _notified_file()
    if not f.exists():
        return
    if task_id is None:
        f.write_text("")
        return
    lines = [
        line for line in f.read_text().splitlines()
        if not (
            line.startswith(f"{task_id}:") or
            line.startswith(f"{task_id}\t")
        )
    ]
    f.write_text("\n".join(lines) + ("\n" if lines else ""))


# ---------------------------------------------------------------------------
# Notify-offset helpers
# ---------------------------------------------------------------------------

def parse_notify_offsets(notify: str) -> List[str]:
    """Split a (possibly comma-separated) notify value into individual offsets.

    Examples
    --------
    parse_notify_offsets("30m")        → ["30m"]
    parse_notify_offsets("30m,2h,1d")  → ["30m", "2h", "1d"]
    """
    if not notify:
        return []
    return [p.strip() for p in notify.split(",") if p.strip()]


_LEAD_RE = re.compile(r"^(\d+)(m|h|d)$", re.IGNORECASE)


def _parse_lead(notify: str) -> Optional[timedelta]:
    """Parse '30m', '2h', '1d' into a timedelta.  Returns None on failure."""
    m = _LEAD_RE.match(notify.strip())
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit == "m":
        return timedelta(minutes=n)
    if unit == "h":
        return timedelta(hours=n)
    return timedelta(days=n)


# ---------------------------------------------------------------------------
# Due-date parser
# ---------------------------------------------------------------------------

def _parse_due(due_str: str) -> Optional[datetime]:
    """Parse a due field (date or datetime) into a datetime. Returns None on failure."""
    try:
        if "T" in due_str:
            return datetime.fromisoformat(due_str)
        from datetime import date
        d = date.fromisoformat(due_str)
        return datetime(d.year, d.month, d.day, 0, 0)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Quiet-hours helper
# ---------------------------------------------------------------------------

def is_quiet_hours(quiet_str: str, now: datetime) -> bool:
    """Return True if *now* falls inside the quiet window described by *quiet_str*.

    Format: "HH:MM-HH:MM"  (e.g. "22:00-08:00").
    Cross-midnight ranges are supported: if start > end, the window wraps.
    Returns False if *quiet_str* is empty or cannot be parsed.
    """
    if not quiet_str or not quiet_str.strip():
        return False
    parts = quiet_str.strip().split("-", 1)
    if len(parts) != 2:
        return False
    try:
        start = _time.fromisoformat(parts[0].strip())
        end   = _time.fromisoformat(parts[1].strip())
    except ValueError:
        return False
    now_t = now.time().replace(second=0, microsecond=0)
    if start <= end:
        # Same-day window (e.g. 09:00-17:00)
        return start <= now_t < end
    else:
        # Cross-midnight window (e.g. 22:00-08:00)
        return now_t >= start or now_t < end


# ---------------------------------------------------------------------------
# Pending-notification detection
# ---------------------------------------------------------------------------

def build_pending(
    tasks: List[Task],
    notified: dict,
    now: Optional[datetime] = None,
    config: Optional[dict] = None,
) -> List[dict]:
    """Return notification payloads for tasks whose window has opened.

    Rules
    -----
    * Tasks that are done, snoozed, or have no due date are skipped.
    * Legacy bare-key entries in *notified* suppress the entire task
      (backward compatibility with .notified files written by older code).
    * For each offset in task.notify, fire when now >= due - lead_time
      and task_id:offset is not in *notified*.
    * An additional "overdue" entry fires once when the task passes its
      due date, regardless of the notify field.
    * If quiet hours are active (from config), return an empty list so
      notifications are deferred to the end of the quiet window.

    Each payload contains
    ---------------------
      id, offset, notify_key, title, due, notify,
      priority, tags, overdue, minutes_until_due
    """
    if now is None:
        now = datetime.now()

    # ---- quiet hours ----
    quiet_str = ""
    if config:
        quiet_str = config.get("notifications", {}).get("quiet_hours", "")
    if is_quiet_hours(quiet_str, now):
        return []

    pending = []

    for task in tasks:
        if task.done:
            continue
        if is_snoozed(task):
            continue
        if not task.due:
            continue

        # Legacy compat: bare task_id entry suppresses all offsets
        if task.id in notified:
            continue

        due_dt = _parse_due(task.due)
        if due_dt is None:
            continue

        minutes_until = int((due_dt - now).total_seconds() / 60)
        overdue = due_dt < now

        # ---- per-offset notifications ----
        for offset in parse_notify_offsets(task.notify or ""):
            key = f"{task.id}:{offset}"
            if key in notified:
                continue
            lead = _parse_lead(offset)
            if lead is None:
                continue
            if now < due_dt - lead:
                continue   # Window not yet open
            pending.append(_payload(task, offset, key, overdue, minutes_until))

        # ---- overdue notification (fires once, independent of notify field) ----
        if overdue:
            key = f"{task.id}:overdue"
            if key not in notified:
                pending.append(_payload(task, "overdue", key, True, minutes_until))

    pending.sort(key=lambda p: (not p["overdue"], p["due"], p["priority"]))
    return pending


def _payload(
    task: Task,
    offset: str,
    notify_key: str,
    overdue: bool,
    minutes_until_due: int,
) -> dict:
    return {
        "id":               task.id,
        "offset":           offset,
        "notify_key":       notify_key,
        "title":            task.title,
        "due":              task.due,
        "notify":           task.notify,
        "priority":         task.priority,
        "tags":             task.tags,
        "overdue":          overdue,
        "minutes_until_due": minutes_until_due,
    }


def get_pending(
    now: Optional[datetime] = None,
    config: Optional[dict] = None,
) -> List[dict]:
    """Convenience wrapper: read tasks and notified state, return pending list."""
    if config is None:
        from ..config import load_config
        config = load_config()
    tasks = read_tasks()
    notified = load_notified()
    return build_pending(tasks, notified, now, config)
