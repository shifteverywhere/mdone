"""
Validation and repair tooling for tasks.md and metadata.json.

Checks performed
----------------
malformed_date      — due or snooze is not ISO 8601; try to normalize via
                      mdone's own parser then dateparser; unfixable if both fail
malformed_notify    — notify is not NNm / NNh / NNd; normalize if possible,
                      otherwise remove the field (still fixable)
duplicate_id        — two tasks share the same ID; keep first, reassign second
invalid_priority    — priority outside 1–4; reset to 4 (none)
structural_orphan   — task appears before any ## section header; move to Inbox
invalid_recurrence  — recur is not daily / weekly / monthly; remove field
orphaned_metadata   — metadata.json entry has no task in tasks.md or archive.md

Exit codes (set by CLI caller)
-------------------------------
0 — no issues (or all issues were fixed)
1 — fixable issues found; run `mdone doctor --fix` to repair
2 — at least one unfixable issue; manual intervention required
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from .models import Task
from .parser import generate_id, parse_line
from .storage import DEFAULT_SECTION

VALID_RECURRENCE = frozenset({"daily", "weekly", "monthly"})

_NOTIFY_RE = re.compile(r"^\d+[mhd](,\d+[mhd])*$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")
_NOTIFY_LOOSE_RE = re.compile(
    r"^(\d+)\s*(m(?:in(?:utes?)?)?|h(?:ours?)?|d(?:ays?)?)$",
    re.IGNORECASE,
)
# Matches any priority:N token — used to find out-of-range values in title text
# (the parser only extracts priority:[1-4], so invalid values land in the title)
_PRIORITY_IN_TEXT_RE = re.compile(r"\bpriority:(\d+)\b")


# ---------------------------------------------------------------------------
# Issue record
# ---------------------------------------------------------------------------

@dataclass
class Issue:
    task_id: Optional[str]  # None for structural / file-level issues
    field: str
    issue_type: str
    description: str
    fixable: bool
    fix_description: str
    before: object
    after: object           # None when unfixable

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "field": self.field,
            "type": self.issue_type,
            "description": self.description,
            "fixable": self.fixable,
            "fix": self.fix_description,
            "before": self.before,
            "after": self.after,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_valid_iso(value: str) -> bool:
    return bool(_ISO_DATE_RE.match(value))


def _try_normalize_date(value: str) -> Optional[str]:
    """Try every available parser to normalize value to ISO 8601.

    Strategy:
      1. mdone's own parse_due_date (handles today, tomorrow, next-friday, etc.)
      2. dateparser (handles natural-language dates like "April 15")
    Returns the normalized ISO string, or None if both fail.
    """
    from .dates import parse_due_date

    result = parse_due_date(value)
    if result != value and _is_valid_iso(result):
        return result

    try:
        import dateparser  # optional dependency
        parsed = dateparser.parse(
            value,
            settings={"RETURN_AS_TIMEZONE_AWARE": False, "PREFER_DAY_OF_MONTH": "first"},
        )
        if parsed:
            return parsed.strftime("%Y-%m-%d")
    except (ImportError, Exception):
        pass

    return None


def _normalize_notify(value: str) -> Optional[str]:
    """Try to normalize a loose notify string to NNm / NNh / NNd (or comma-separated).

    Accepts comma-separated values such as "30 min, 2 hours, 1d".
    Returns the normalized form, or None if any part cannot be salvaged
    (in which case the caller should remove the field entirely).
    """
    parts = [p.strip() for p in value.strip().split(",") if p.strip()]
    if not parts:
        return None
    normalized = []
    for part in parts:
        m = _NOTIFY_LOOSE_RE.match(part)
        if not m:
            return None  # any unrecognised part → give up on the whole value
        unit = m.group(2)[0].lower()  # 'm', 'h', or 'd'
        normalized.append(f"{m.group(1)}{unit}")
    return ",".join(normalized)


# ---------------------------------------------------------------------------
# Individual check functions
# ---------------------------------------------------------------------------

def check_malformed_dates(tasks: List[Task]) -> List[Issue]:
    issues = []
    for task in tasks:
        for field_name in ("due", "snooze"):
            val = getattr(task, field_name)
            if val is None or _is_valid_iso(val):
                continue
            normalized = _try_normalize_date(val)
            if normalized:
                issues.append(Issue(
                    task_id=task.id, field=field_name,
                    issue_type="malformed_date",
                    description=f"{field_name} '{val}' is not ISO 8601",
                    fixable=True,
                    fix_description=f"normalize to '{normalized}'",
                    before=val, after=normalized,
                ))
            else:
                issues.append(Issue(
                    task_id=task.id, field=field_name,
                    issue_type="malformed_date",
                    description=(
                        f"{field_name} '{val}' cannot be parsed — "
                        "edit the task manually to set a valid date or remove the field"
                    ),
                    fixable=False,
                    fix_description="remove manually",
                    before=val, after=None,
                ))
    return issues


def check_malformed_notify(tasks: List[Task]) -> List[Issue]:
    issues = []
    for task in tasks:
        val = task.notify
        if val is None or _NOTIFY_RE.match(val):
            continue
        normalized = _normalize_notify(val)
        if normalized:
            issues.append(Issue(
                task_id=task.id, field="notify",
                issue_type="malformed_notify",
                description=(
                    f"notify '{val}' is not in NNm / NNh / NNd "
                    "(or comma-separated) format"
                ),
                fixable=True,
                fix_description=f"normalize to '{normalized}'",
                before=val, after=normalized,
            ))
        else:
            issues.append(Issue(
                task_id=task.id, field="notify",
                issue_type="malformed_notify",
                description=(
                    f"notify '{val}' cannot be normalized — will be removed"
                ),
                fixable=True,
                fix_description="remove notify field",
                before=val, after=None,
            ))
    return issues


def check_duplicate_ids(tasks: List[Task]) -> List[Issue]:
    issues = []
    seen: dict[str, str] = {}   # id → title of first occurrence
    for task in tasks:
        if task.id in seen:
            new_id = generate_id()
            issues.append(Issue(
                task_id=task.id, field="id",
                issue_type="duplicate_id",
                description=(
                    f"ID '{task.id}' is shared by '{seen[task.id]}'"
                    f" and '{task.title}' — keeping first, reassigning second"
                ),
                fixable=True,
                fix_description=f"reassign second task to '{new_id}'",
                before=task.id, after=new_id,
            ))
        else:
            seen[task.id] = task.title
    return issues


def check_invalid_priorities(tasks: List[Task]) -> List[Issue]:
    """Detect out-of-range priority values.

    The parser regex only extracts priority:1–4, so priority:9 (for example)
    is NOT extracted as a field — it stays as literal text in task.title.
    We therefore also scan the title for embedded priority:N tokens.
    """
    issues = []
    for task in tasks:
        if task.priority not in range(1, 5):
            issues.append(Issue(
                task_id=task.id, field="priority",
                issue_type="invalid_priority",
                description=f"priority '{task.priority}' is not in range 1–4",
                fixable=True,
                fix_description="set to 4 (none / default)",
                before=task.priority, after=4,
            ))
        else:
            # Parser only extracts priority:1-4; out-of-range values land in title text
            m = _PRIORITY_IN_TEXT_RE.search(task.title)
            if m:
                n = int(m.group(1))
                if n not in range(1, 5):
                    issues.append(Issue(
                        task_id=task.id, field="priority",
                        issue_type="invalid_priority",
                        description=(
                            f"'priority:{n}' in title text is not in range 1–4"
                        ),
                        fixable=True,
                        fix_description=(
                            f"remove 'priority:{n}' from title and set priority to 4"
                        ),
                        before=n, after=4,
                    ))
    return issues


def check_structural_orphans(filepath: Path) -> List[Issue]:
    """Find tasks that appear before the first ## section header."""
    issues = []
    seen_header = False
    for line in filepath.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            seen_header = True
            continue
        if not seen_header:
            task = parse_line(line)
            if task:
                issues.append(Issue(
                    task_id=task.id, field="section",
                    issue_type="structural_orphan",
                    description=(
                        f"task '{task.id}' ({task.title!r}) appears before"
                        " any section header"
                    ),
                    fixable=True,
                    fix_description=(
                        f"place under '## {DEFAULT_SECTION.capitalize()}'"
                    ),
                    before=None, after=DEFAULT_SECTION,
                ))
    return issues


def check_recurrence_syntax(tasks: List[Task]) -> List[Issue]:
    issues = []
    for task in tasks:
        val = task.recur
        if val is None or val in VALID_RECURRENCE:
            continue
        issues.append(Issue(
            task_id=task.id, field="recur",
            issue_type="invalid_recurrence",
            description=(
                f"recur '{val}' is not one of: daily, weekly, monthly"
            ),
            fixable=True,
            fix_description="remove recur field",
            before=val, after=None,
        ))
    return issues


def check_orphaned_metadata(
    tasks: List[Task],
    archive_tasks: Optional[List[Task]] = None,
) -> List[Issue]:
    """Return issues for metadata entries with no corresponding task."""
    from .metadata import read_all_meta
    issues = []
    known_ids = {t.id for t in tasks} | {t.id for t in (archive_tasks or [])}
    for meta_id in read_all_meta():
        if meta_id not in known_ids:
            issues.append(Issue(
                task_id=meta_id, field="metadata",
                issue_type="orphaned_metadata",
                description=(
                    f"metadata entry '{meta_id}' has no corresponding task"
                    " in tasks.md or archive.md"
                ),
                fixable=True,
                fix_description="remove orphaned metadata entry",
                before=meta_id, after=None,
            ))
    return issues


# ---------------------------------------------------------------------------
# Run all checks
# ---------------------------------------------------------------------------

def run_checks(
    tasks: List[Task],
    filepath: Path,
    archive_tasks: Optional[List[Task]] = None,
    task_id: Optional[str] = None,
) -> List[Issue]:
    """Run all checks and return every issue found.

    If task_id is given, per-task checks are scoped to that task only.
    File-level checks (structural orphans, orphaned metadata, duplicate IDs)
    are always run against the full task list so nothing is missed.
    """
    target = [t for t in tasks if t.id == task_id] if task_id else tasks

    issues: List[Issue] = []
    issues.extend(check_malformed_dates(target))
    issues.extend(check_malformed_notify(target))
    issues.extend(check_invalid_priorities(target))
    issues.extend(check_recurrence_syntax(target))

    if task_id:
        # For duplicates: include only those involving the requested task
        all_dups = check_duplicate_ids(tasks)
        issues.extend(i for i in all_dups if i.task_id == task_id)
    else:
        issues.extend(check_duplicate_ids(tasks))
        issues.extend(check_structural_orphans(filepath))
        issues.extend(check_orphaned_metadata(tasks, archive_tasks))

    return issues


# ---------------------------------------------------------------------------
# Apply fixes (in-memory)
# ---------------------------------------------------------------------------

def apply_fixes(
    issues: List[Issue],
    tasks: List[Task],
) -> Tuple[List[Task], List[Issue], List[Issue], List[str]]:
    """Apply all fixable repairs to the task list in-place.

    Returns
    -------
    tasks               — the (mutated) task list
    fixed_issues        — issues that were repaired
    unfixable_issues    — issues that could not be repaired automatically
    orphaned_meta_ids   — metadata IDs to delete (caller handles the write
                          so dry-run mode can skip it)
    """
    fixed: List[Issue] = []
    unfixable: List[Issue] = []
    orphaned_meta_ids: List[str] = []

    for issue in issues:
        if not issue.fixable:
            unfixable.append(issue)
            continue

        # Metadata cleanup is handled by the caller (no task mutation needed)
        if issue.issue_type == "orphaned_metadata":
            orphaned_meta_ids.append(issue.task_id)
            fixed.append(issue)
            continue

        # Duplicate ID: rename the second occurrence, keeping the first intact
        if issue.issue_type == "duplicate_id":
            found_first = False
            for t in tasks:
                if t.id == issue.before:
                    if found_first:
                        t.id = issue.after
                        break
                    found_first = True
            fixed.append(issue)
            continue

        # Structural orphan: task.section is already DEFAULT_SECTION from read_tasks;
        # writing back via write_tasks() places it under the correct header
        if issue.issue_type == "structural_orphan":
            task = next((t for t in tasks if t.id == issue.task_id), None)
            if task:
                task.section = issue.after
                fixed.append(issue)
            else:
                unfixable.append(issue)
            continue

        # All other per-task field repairs
        task = next((t for t in tasks if t.id == issue.task_id), None)
        if task is None:
            unfixable.append(issue)
            continue

        field = issue.field
        if field in ("due", "snooze", "notify", "recur"):
            setattr(task, field, issue.after)
            fixed.append(issue)
        elif field == "priority":
            task.priority = issue.after
            # Also strip any embedded priority:N token from the title
            # (the parser leaves out-of-range values in title text)
            task.title = re.sub(r"\bpriority:\d+\b", "", task.title).strip()
            fixed.append(issue)
        else:
            unfixable.append(issue)

    return tasks, fixed, unfixable, orphaned_meta_ids
