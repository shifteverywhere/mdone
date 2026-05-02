"""
Parse and serialize task lines.

Format:
  - [ ] Title words @tag1 @tag2 +ctx due:YYYY-MM-DD priority:1 recur:weekly notify:30m snooze:YYYY-MM-DDTHH:MM id:abc123
"""

import re
import secrets
import string
from typing import Optional

from .models import Task

# Matches the full task line
_TASK_LINE_RE = re.compile(r"^- \[([ x])\] (.+)$")

# Key:value fields — matched and stripped to recover the plain title
_FIELD_RE = {
    "id":               re.compile(r"\bid:([A-Za-z0-9]+)"),
    "due":              re.compile(r"\bdue:(\S+)"),
    "recur":            re.compile(r"\brecur:(\S+)"),
    "priority":         re.compile(r"\bpriority:([1-4])"),
    "notify":           re.compile(r"\bnotify:(\S+)"),
    "snooze":           re.compile(r"\bsnooze:(\S+)"),
    "idempotency_key":  re.compile(r"\bidempotency_key:(\S+)"),
}

# Inline tokens — may include leading whitespace in the match so stripping
# them from the body doesn't leave stray spaces
_TAG_RE = re.compile(r"(?:^|\s)@(\w+)")
_CTX_RE = re.compile(r"(?:^|\s)\+(\w+)")


def generate_id() -> str:
    """Return an 8-character random alphanumeric ID."""
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(8))


def parse_line(line: str) -> Optional[Task]:
    """Parse a single Markdown task line into a Task, or return None."""
    m = _TASK_LINE_RE.match(line.rstrip())
    if not m:
        return None

    done = m.group(1) == "x"
    body = m.group(2)

    # Extract key:value fields
    fields: dict[str, Optional[str]] = {}
    for key, pattern in _FIELD_RE.items():
        hit = pattern.search(body)
        fields[key] = hit.group(1) if hit else None

    # Extract list-valued tokens
    tags = _TAG_RE.findall(body)
    contexts = _CTX_RE.findall(body)

    # Strip all structured tokens to isolate the plain title
    title = body
    for pattern in _FIELD_RE.values():
        title = pattern.sub("", title)
    title = _TAG_RE.sub("", title)
    title = _CTX_RE.sub("", title)
    title = re.sub(r"\s+", " ", title).strip()

    return Task(
        title=title,
        id=fields["id"] or generate_id(),
        done=done,
        tags=tags,
        contexts=contexts,
        due=fields["due"],
        recur=fields["recur"],
        priority=int(fields["priority"]) if fields["priority"] else 4,
        notify=fields["notify"],
        snooze=fields["snooze"],
        idempotency_key=fields["idempotency_key"],
    )


def serialize_task(task: Task) -> str:
    """Serialize a Task back to a Markdown task line."""
    checkbox = "x" if task.done else " "
    parts = [task.title]

    for tag in task.tags:
        parts.append(f"@{tag}")
    for ctx in task.contexts:
        parts.append(f"+{ctx}")
    if task.due:
        parts.append(f"due:{task.due}")
    if task.recur:
        parts.append(f"recur:{task.recur}")
    if task.priority != 4:
        parts.append(f"priority:{task.priority}")
    if task.notify:
        parts.append(f"notify:{task.notify}")
    if task.snooze:
        parts.append(f"snooze:{task.snooze}")
    if task.idempotency_key:
        parts.append(f"idempotency_key:{task.idempotency_key}")
    parts.append(f"id:{task.id}")

    return f"- [{checkbox}] {' '.join(parts)}"
