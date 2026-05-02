"""
File-backed storage for tasks.

tasks.md  — active tasks, grouped under section headers (## Inbox, ## Today, …)
archive.md — append-only log of completed tasks (flat, no sections)

Set the TODO_DIR environment variable to override the default ~/.todo path.
This is used in tests to point at a temporary directory.
"""

import os
from pathlib import Path
from typing import List, Optional

from .models import Task
from .parser import parse_line, serialize_task

# Ordered list of all valid section names (lowercase).
SECTIONS = ["inbox", "today", "upcoming", "someday", "waiting"]
DEFAULT_SECTION = "inbox"

_FOOTER = "\n---\nPowered by ¯\\(ツ)/¯mdone\n"


def get_todo_dir() -> Path:
    custom = os.environ.get("TODO_DIR")
    return Path(custom) if custom else Path.home() / ".todo"


def _tasks_file() -> Path:
    return get_todo_dir() / "tasks.md"


def _archive_file() -> Path:
    return get_todo_dir() / "archive.md"


def _initial_tasks_content() -> str:
    """Return the default tasks.md content: one header per section, all empty."""
    blocks = [f"## {s.capitalize()}" for s in SECTIONS]
    return "\n\n".join(blocks) + _FOOTER


def _ensure_dir() -> None:
    get_todo_dir().mkdir(parents=True, exist_ok=True)
    tasks = _tasks_file()
    if not tasks.exists():
        tasks.write_text(_initial_tasks_content())


# ---------------------------------------------------------------------------
# Core read / write
# ---------------------------------------------------------------------------

def read_tasks() -> List[Task]:
    """Read tasks from tasks.md, assigning each task its section from the
    nearest preceding ## header."""
    _ensure_dir()
    tasks = []
    current_section = DEFAULT_SECTION
    for line in _tasks_file().read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            name = stripped[3:].strip().lower()
            if name in SECTIONS:
                current_section = name
            continue
        task = parse_line(line)
        if task:
            task.section = current_section
            tasks.append(task)
    return tasks


def write_tasks(tasks: List[Task]) -> None:
    """Write tasks to tasks.md, grouped under their section headers.
    All section headers are always written (even if the section is empty)."""
    _ensure_dir()
    by_section: dict = {s: [] for s in SECTIONS}
    for t in tasks:
        s = t.section if t.section in SECTIONS else DEFAULT_SECTION
        by_section[s].append(t)

    blocks = []
    for section in SECTIONS:
        lines = [f"## {section.capitalize()}"]
        lines.extend(serialize_task(t) for t in by_section[section])
        blocks.append("\n".join(lines))

    _tasks_file().write_text("\n\n".join(blocks) + _FOOTER)


# ---------------------------------------------------------------------------
# Higher-level helpers
# ---------------------------------------------------------------------------

def read_archive_tasks() -> List[Task]:
    """Read completed tasks from archive.md (flat, no section headers)."""
    _ensure_dir()
    arc = _archive_file()
    if not arc.exists():
        return []
    tasks = []
    for line in arc.read_text().splitlines():
        task = parse_line(line)
        if task:
            tasks.append(task)
    return tasks


def find_task(task_id: str) -> Optional[Task]:
    for task in read_tasks():
        if task.id == task_id:
            return task
    return None


def add_task(task: Task) -> None:
    tasks = read_tasks()
    tasks.append(task)
    write_tasks(tasks)


def update_task(task: Task) -> bool:
    """Replace the task with the matching id. Returns False if not found."""
    tasks = read_tasks()
    for i, t in enumerate(tasks):
        if t.id == task.id:
            tasks[i] = task
            write_tasks(tasks)
            return True
    return False


def delete_task(task_id: str) -> bool:
    """Remove a task by id. Returns False if not found."""
    tasks = read_tasks()
    filtered = [t for t in tasks if t.id != task_id]
    if len(filtered) == len(tasks):
        return False
    write_tasks(filtered)
    return True


def archive_task(task: Task) -> None:
    """Append the task (marked done) to archive.md, keeping the footer at the end."""
    _ensure_dir()
    task.done = True
    line = serialize_task(task)
    archive = _archive_file()
    existing = archive.read_text() if archive.exists() else ""
    # Strip trailing footer if present so we can re-add it after the new line
    if existing.endswith(_FOOTER):
        existing = existing[: -len(_FOOTER)]
    archive.write_text(existing + line + "\n" + _FOOTER)
