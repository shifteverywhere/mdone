"""
Notification checker — determines which tasks are pending notification
and manages the .notified deduplication state file.

A task is pending notification when ALL of the following hold:
  1. It has a due: field
  2. It has a notify: lead time  OR  it is overdue
  3. The notification window has opened  (now >= due - lead_time)
  4. Its id is not in .notified
  5. It is not done
  6. It is not snoozed
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
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
    """Return {task_id: iso_datetime_string} for all already-sent notifications."""
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


def mark_sent(task_ids: List[str]) -> None:
    """Append task_ids to .notified with the current timestamp."""
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M")
    with _notified_file().open("a") as f:
        for tid in task_ids:
            f.write(f"{tid}\t{now_str}\n")


def reset_notified(task_id: Optional[str] = None) -> None:
    """
    Clear .notified entirely, or remove a single task_id entry.
    """
    f = _notified_file()
    if not f.exists():
        return
    if task_id is None:
        f.write_text("")
        return
    lines = [
        line for line in f.read_text().splitlines()
        if not line.startswith(task_id + "\t")
    ]
    f.write_text("\n".join(lines) + ("\n" if lines else ""))


# ---------------------------------------------------------------------------
# Lead-time parser
# ---------------------------------------------------------------------------

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
# Pending-notification detection
# ---------------------------------------------------------------------------

def _parse_due(due_str: str) -> Optional[datetime]:
    """Parse a due field (date or datetime) into a datetime. Returns None on failure."""
    try:
        if "T" in due_str:
            return datetime.fromisoformat(due_str)
        # Date-only: treat as midnight
        from datetime import date
        d = date.fromisoformat(due_str)
        return datetime(d.year, d.month, d.day, 0, 0)
    except ValueError:
        return None


def build_pending(tasks: List[Task], notified: dict, now: Optional[datetime] = None) -> List[dict]:
    """
    Return a list of notification payloads for tasks whose window has opened
    and which have not already been notified.

    Each payload dict contains:
        id, title, due, notify, priority, tags, overdue, minutes_until_due
    """
    if now is None:
        now = datetime.now()

    pending = []

    for task in tasks:
        if task.done:
            continue
        if is_snoozed(task):
            continue
        if not task.due:
            continue
        if task.id in notified:
            continue

        due_dt = _parse_due(task.due)
        if due_dt is None:
            continue

        minutes_until = int((due_dt - now).total_seconds() / 60)
        overdue = due_dt < now

        # Window check: notify field present → open when now >= due - lead
        # Overdue tasks without notify: also surface (with overdue=True)
        if task.notify:
            lead = _parse_lead(task.notify)
            if lead is None:
                continue
            window_open = now >= (due_dt - lead)
            if not window_open:
                continue
        else:
            # No notify field → only surface if already overdue
            if not overdue:
                continue

        pending.append({
            "id": task.id,
            "title": task.title,
            "due": task.due,
            "notify": task.notify,
            "priority": task.priority,
            "tags": task.tags,
            "overdue": overdue,
            "minutes_until_due": minutes_until,
        })

    # Sort: overdue first, then by due datetime, then by priority
    pending.sort(key=lambda p: (not p["overdue"], p["due"], p["priority"]))
    return pending


def get_pending(now: Optional[datetime] = None) -> List[dict]:
    """Convenience wrapper: read tasks and notified state, return pending list."""
    tasks = read_tasks()
    notified = load_notified()
    return build_pending(tasks, notified, now)
