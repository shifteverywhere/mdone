"""
CLI entry point.

Exit codes:
  0  success
  1  task not found
  2  parse / input error
  3  no tasks matched the filter
"""

import json
import sys
import time
from datetime import date, timedelta

import click

from .models import Task
from .parser import generate_id, parse_line
from .storage import (
    SECTIONS,
    DEFAULT_SECTION,
    add_task,
    archive_task,
    delete_task,
    find_task,
    read_tasks,
    update_task,
    write_tasks,
)
from .dates import (
    is_snoozed,
    parse_due_date,
    parse_snooze_duration,
    spawn_next_occurrence,
)
from .nlp import parse_natural
from .notify.checker import get_pending, mark_sent, reset_notified
from .notify.backends import get_backend
from .config import (
    load_config,
    get_notification_backend_name,
    get_poll_interval,
    get_default_notify,
    get_default_tags,
    get_default_priority,
    get_date_format,
    write_default_config,
)
from .search import search_tasks
from .completions import detect_shell, get_script, install as install_completions


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_task_string(task_string: str) -> Task:
    """Parse a free-form task string and normalise the due date if present."""
    task = parse_line(f"- [ ] {task_string}")
    if not task:
        click.echo("Error: could not parse task string.", err=True)
        sys.exit(2)
    if task.due:
        task.due = parse_due_date(task.due)
    return task


def _emit(obj, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(obj, indent=2))


def _fmt_due(due_str: str, date_format: str) -> str:
    """Format a stored ISO due string using date_format for human display."""
    if not due_str:
        return ""
    try:
        from datetime import datetime
        if "T" in due_str:
            dt = datetime.fromisoformat(due_str)
            return dt.strftime(date_format) + due_str[len(due_str.split("T")[0]):]
        from datetime import date as _date
        return _date.fromisoformat(due_str).strftime(date_format)
    except ValueError:
        return due_str


def _task_row(t: Task, date_format: str = "%Y-%m-%d") -> str:
    status = "x" if t.done else " "
    pri = f"p{t.priority}" if t.priority < 4 else "  "
    tags = (" " + " ".join(f"@{tag}" for tag in t.tags)) if t.tags else ""
    due = (f" due:{_fmt_due(t.due, date_format)}") if t.due else ""
    snooze = f" [snoozed until {t.snooze}]" if t.snooze else ""
    return f"[{status}] {t.id}  {pri}  {t.title}{tags}{due}{snooze}"


def _section(title: str, tasks: list) -> None:
    click.echo(f"\n{title} ({len(tasks)})")
    click.echo("─" * 40)
    if tasks:
        for t in tasks:
            click.echo(_task_row(t))
    else:
        click.echo("  (none)")


def _sort_within_sections(tasks: list, sort_by: str) -> list:
    """Return a new list with tasks sorted within each section.

    Sections are kept in canonical order (SECTIONS). The sort is stable, so
    tasks that compare equal retain their previous relative order.
    """
    def _key(t):
        if sort_by == "priority":
            return (t.priority, t.due or "zzzzz", t.title.lower())
        if sort_by == "due":
            return (t.due or "zzzzz", t.priority, t.title.lower())
        return t.title.lower()  # title

    by_section: dict = {s: [] for s in SECTIONS}
    for t in tasks:
        s = t.section if t.section in SECTIONS else DEFAULT_SECTION
        by_section[s].append(t)

    result = []
    for s in SECTIONS:
        result.extend(sorted(by_section[s], key=_key))
    return result


def _auto_section(task) -> str:
    """Infer the natural section for a task based on its due date."""
    if task.due:
        today = date.today().isoformat()
        if task.due.split("T")[0] <= today:
            return "today"
        return "upcoming"
    return DEFAULT_SECTION


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(version="1.0.0", prog_name="mdone",
                      message="¯\\(ツ)/¯mdone  %(version)s")
def cli():
    """¯\\(ツ)/¯mdone — Markdown-based todo manager."""


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------

@cli.command("add")
@click.argument("task_string")
@click.option("--natural", "-n", is_flag=True,
              help="Interpret TASK_STRING as plain English (NLP mode)")
@click.option(
    "--section", "-s", default=None,
    type=click.Choice(SECTIONS),
    help="Section to add the task to (default: auto-assigned from due date)",
)
@click.option("--dry-run", is_flag=True,
              help="Show the parsed task as JSON without saving (useful for agents)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def cmd_add(task_string: str, natural: bool, section: str, dry_run: bool, as_json: bool) -> None:
    """Add a new task.

    Tasks are automatically placed in the most appropriate section:
    tasks due today or earlier go to Today, future due dates go to Upcoming,
    and tasks with no due date land in Inbox.  Override with --section.

    \b
    Sections: inbox | today | upcoming | someday | waiting

    Mini-syntax mode (default):

    \b
      todo add "Buy milk @shopping due:tomorrow priority:2"
      todo add "Stand-up @work due:2026-04-15T09:00 recur:daily"
      todo add "Parked idea" --section someday

    Natural language mode (--natural / -n):

    \b
      todo add -n "remind me to call Alice next Friday at 3pm"
      todo add -n "urgent: fix the login bug tomorrow"
    """
    config = load_config()

    if natural:
        parsed = parse_natural(task_string)
        task = Task(
            title=parsed["title"],
            id=generate_id(),
            tags=parsed["tags"],
            due=parsed["due"],
            priority=parsed["priority"],
        )
    else:
        task = _parse_task_string(task_string)
        task.id = generate_id()

    # Apply config defaults (only when not already set by the task string)
    default_tags = get_default_tags(config)
    for dt in default_tags:
        if dt not in task.tags:
            task.tags.append(dt)

    if task.priority == 4:
        task.priority = get_default_priority(config)

    if task.notify is None:
        dn = get_default_notify(config)
        if dn:
            task.notify = dn

    # Section: explicit flag > auto-assigned from due date
    task.section = section if section else _auto_section(task)

    if dry_run:
        # Always emit JSON for dry-run — it's a machine-readable preview
        click.echo(json.dumps(task.to_dict(), indent=2))
        return

    add_task(task)

    if as_json:
        _emit(task.to_dict(), as_json=True)
    else:
        click.echo(f"Added [{task.section}]: {task.id}  {task.title}")


# ---------------------------------------------------------------------------
# list / ls
# ---------------------------------------------------------------------------

@cli.command("list")
@click.option("--tag", "-t", default=None, help="Filter by @tag")
@click.option("--priority", "-p", type=int, default=None, help="Filter by priority (1–4)")
@click.option("--due", default=None, metavar="DATE",
              help="Filter by due date (today | YYYY-MM-DD | relative)")
@click.option("--overdue", is_flag=True, help="Show tasks past their due date")
@click.option("--done", "show_done", is_flag=True,
              help="Show completed tasks instead of open ones")
@click.option("--all", "show_all", is_flag=True,
              help="Include snoozed tasks (hidden by default)")
@click.option(
    "--section", "-s", default=None,
    type=click.Choice(SECTIONS),
    help="Filter to a specific section",
)
@click.option(
    "--sort", default="priority",
    type=click.Choice(["priority", "due", "title"]),
    show_default=True, help="Sort order",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def cmd_list(tag, priority, due, overdue, show_done, show_all, section, sort, as_json):
    """List tasks with optional filters.

    Without --section, tasks are grouped under their section headers.
    Snoozed tasks are hidden unless --all is passed.

    \b
      todo list                       # all open tasks, grouped by section
      todo list --section today       # only tasks in Today
      todo list --tag work            # @work tasks, grouped by section
    """
    tasks = read_tasks()

    # Status filter
    if not show_done:
        tasks = [t for t in tasks if not t.done]
    else:
        tasks = [t for t in tasks if t.done]

    # Hide snoozed tasks unless --all
    if not show_all:
        tasks = [t for t in tasks if not is_snoozed(t)]

    if section:
        tasks = [t for t in tasks if t.section == section]

    if tag:
        tasks = [t for t in tasks if tag in t.tags]

    if priority is not None:
        tasks = [t for t in tasks if t.priority == priority]

    today_str = date.today().isoformat()
    if overdue:
        tasks = [t for t in tasks if t.due and t.due < today_str]
    elif due:
        due_norm = parse_due_date(due)
        tasks = [t for t in tasks if t.due and t.due.startswith(due_norm)]

    def _sort_key(t: Task):
        if sort == "priority":
            return (t.priority, t.due or "zzzzz")
        if sort == "due":
            return (t.due or "zzzzz", t.priority)
        return t.title.lower()

    tasks.sort(key=_sort_key)

    if as_json:
        _emit([t.to_dict() for t in tasks], as_json=True)
        return

    if not tasks:
        click.echo("No tasks found.")
        sys.exit(3)

    # Flat output when a specific section or done-view is requested
    if section or show_done:
        for t in tasks:
            click.echo(_task_row(t))
        return

    # Grouped output: one block per section, skip empty sections
    config = load_config()
    date_fmt = get_date_format(config)
    printed_any = False
    for sec in SECTIONS:
        sec_tasks = [t for t in tasks if t.section == sec]
        if not sec_tasks:
            continue
        click.echo(f"\n## {sec.capitalize()} ({len(sec_tasks)})")
        click.echo("─" * 40)
        for t in sec_tasks:
            click.echo(_task_row(t, date_fmt))
        printed_any = True
    if not printed_any:
        click.echo("No tasks found.")
        sys.exit(3)


cli.add_command(cmd_list, name="ls")


# ---------------------------------------------------------------------------
# done
# ---------------------------------------------------------------------------

@cli.command("done")
@click.argument("task_ids", nargs=-1, required=True)
@click.option("--dry-run", is_flag=True,
              help="Preview what would be archived/spawned without writing")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def cmd_done(task_ids, dry_run, as_json):
    """Mark one or more tasks as complete.

    Recurring tasks automatically spawn their next occurrence.
    """
    results = []
    for task_id in task_ids:
        task = find_task(task_id)
        if not task:
            click.echo(f"Error: task '{task_id}' not found.", err=True)
            sys.exit(1)

        next_task = spawn_next_occurrence(task)

        if not dry_run:
            archive_task(task)    # marks done=True, appends to archive.md
            delete_task(task_id)  # removes from tasks.md
            if next_task:
                add_task(next_task)

        results.append({
            "completed": task.to_dict(),
            "spawned": next_task.to_dict() if next_task else None,
            "dry_run": dry_run,
        })

    if as_json or dry_run:
        click.echo(json.dumps(results, indent=2))
    else:
        for r in results:
            click.echo(f"Done: {r['completed']['id']}  {r['completed']['title']}")
            if r["spawned"]:
                s = r["spawned"]
                click.echo(f"  ↻  Next: {s['id']}  {s['title']}  due:{s['due']}")


# ---------------------------------------------------------------------------
# delete / rm
# ---------------------------------------------------------------------------

@cli.command("delete")
@click.argument("task_id")
@click.option("--dry-run", is_flag=True, help="Preview deletion without writing")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def cmd_delete(task_id, dry_run, as_json):
    """Delete a task permanently (no archive)."""
    task = find_task(task_id)
    if not task:
        click.echo(f"Error: task '{task_id}' not found.", err=True)
        sys.exit(1)

    if not dry_run:
        delete_task(task_id)

    result = {"deleted": task_id, "task": task.to_dict(), "dry_run": dry_run}
    if as_json or dry_run:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Deleted: {task_id}")


cli.add_command(cmd_delete, name="rm")


# ---------------------------------------------------------------------------
# edit
# ---------------------------------------------------------------------------

@cli.command("edit")
@click.argument("task_id")
@click.argument("task_string", required=False)
@click.option(
    "--set", "set_fields", multiple=True, metavar="FIELD:VALUE",
    help="Set a specific field, e.g. --set priority:1  (repeatable)",
)
@click.option("--dry-run", is_flag=True, help="Preview the result without saving")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def cmd_edit(task_id, task_string, set_fields, dry_run, as_json):
    """Edit a task.

    \b
    Replace the full task definition:
      todo edit abc123 "New title @newtag due:next-monday"

    Update individual fields:
      todo edit abc123 --set priority:1 --set due:tomorrow
    """
    task = find_task(task_id)
    if not task:
        click.echo(f"Error: task '{task_id}' not found.", err=True)
        sys.exit(1)

    if task_string:
        updated = _parse_task_string(task_string)  # due normalised inside
        updated.id = task.id
        updated.done = task.done
        task = updated

    for field_expr in set_fields:
        key, _, value = field_expr.partition(":")
        if key == "priority":
            task.priority = int(value)
        elif key == "due":
            task.due = parse_due_date(value)
        elif key == "recur":
            task.recur = value
        elif key == "notify":
            task.notify = value
        elif key == "snooze":
            task.snooze = parse_snooze_duration(value)
        elif key == "title":
            task.title = value
        elif key == "section":
            if value not in SECTIONS:
                click.echo(f"Error: unknown section '{value}'. "
                           f"Choose from: {', '.join(SECTIONS)}", err=True)
                sys.exit(2)
            task.section = value
        else:
            click.echo(f"Error: unknown field '{key}'.", err=True)
            sys.exit(2)

    if not dry_run:
        update_task(task)

    if as_json or dry_run:
        click.echo(json.dumps(task.to_dict(), indent=2))
    else:
        click.echo(f"Updated: {task.id}  {task.title}")


# ---------------------------------------------------------------------------
# snooze
# ---------------------------------------------------------------------------

@cli.command("snooze")
@click.argument("task_id")
@click.argument("duration", required=False)
@click.option("--clear", is_flag=True, help="Remove the snooze from a task")
@click.option("--dry-run", is_flag=True, help="Preview without saving")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def cmd_snooze(task_id, duration, clear, dry_run, as_json):
    """Snooze a task until a given time, hiding it from the default list view.

    \b
      todo snooze abc123 30m
      todo snooze abc123 2h
      todo snooze abc123 1d
      todo snooze abc123 2026-04-20T09:00
      todo snooze abc123 --clear
    """
    task = find_task(task_id)
    if not task:
        click.echo(f"Error: task '{task_id}' not found.", err=True)
        sys.exit(1)

    if clear:
        task.snooze = None
        if not dry_run:
            update_task(task)
        if as_json or dry_run:
            click.echo(json.dumps(task.to_dict(), indent=2))
        else:
            click.echo(f"Snooze cleared: {task.id}  {task.title}")
        return

    if not duration:
        click.echo("Error: provide a duration (e.g. 2h) or --clear.", err=True)
        sys.exit(2)

    try:
        task.snooze = parse_snooze_duration(duration)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(2)

    if not dry_run:
        update_task(task)

    if as_json or dry_run:
        click.echo(json.dumps(task.to_dict(), indent=2))
    else:
        click.echo(f"Snoozed: {task.id}  {task.title}  until {task.snooze}")


# ---------------------------------------------------------------------------
# recap
# ---------------------------------------------------------------------------

@cli.command("recap")
@click.option("--week", is_flag=True, help="Show the full 7-day lookahead")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def cmd_recap(week, as_json):
    """Summarise overdue tasks and what's due today (or this week).

    \b
      todo recap           # overdue + today
      todo recap --week    # overdue + next 7 days
    """
    today = date.today()
    today_str = today.isoformat()
    cutoff_str = (today + timedelta(days=7)).isoformat()

    tasks = [t for t in read_tasks() if not t.done and not is_snoozed(t)]

    overdue = sorted(
        [t for t in tasks if t.due and t.due < today_str],
        key=lambda t: (t.due, t.priority),
    )

    if week:
        upcoming = sorted(
            [t for t in tasks if t.due and today_str <= t.due <= cutoff_str],
            key=lambda t: (t.due, t.priority),
        )
        no_due = [t for t in tasks if not t.due]

        if as_json:
            _emit({
                "overdue": [t.to_dict() for t in overdue],
                "upcoming": [t.to_dict() for t in upcoming],
                "no_due_date": [t.to_dict() for t in no_due],
            }, as_json=True)
        else:
            _section("OVERDUE", overdue)
            label = f"UPCOMING — {today_str} → {cutoff_str}"
            _section(label, upcoming)
    else:
        today_tasks = sorted(
            [t for t in tasks if t.due and t.due.startswith(today_str)],
            key=lambda t: (t.due, t.priority),
        )

        if as_json:
            _emit({
                "overdue": [t.to_dict() for t in overdue],
                "today": [t.to_dict() for t in today_tasks],
            }, as_json=True)
        else:
            _section("OVERDUE", overdue)
            _section(f"TODAY — {today.strftime('%a %b %d')}", today_tasks)


# ---------------------------------------------------------------------------
# triage
# ---------------------------------------------------------------------------

@cli.command("triage")
@click.option("--json", "as_json", is_flag=True,
              help="Non-interactive: print untriaged tasks as JSON and exit")
def cmd_triage(as_json):
    """Interactively assign due dates and priorities to unscheduled tasks.

    A task needs triage when it has no due date AND no priority set (p4).

    \b
      Interactive (human):   todo triage
      Agent / script:        todo triage --json
    """
    candidates = [
        t for t in read_tasks()
        if not t.done and not is_snoozed(t) and t.due is None and t.priority == 4
    ]

    if as_json:
        _emit([t.to_dict() for t in candidates], as_json=True)
        return

    if not candidates:
        click.echo("No tasks need triage. ✓")
        return

    total = len(candidates)
    click.echo(f"\n{total} task(s) need triage.\n")

    for idx, task in enumerate(candidates):
        while True:
            click.echo("─" * 50)
            click.echo(f" {idx + 1}/{total}  {_task_row(task)}")
            click.echo("─" * 50)
            click.echo("  [d]ue  [p]riority  [t]ag  [s]kip  [q]uit")

            action = click.prompt("", prompt_suffix="> ",
                                  default="s", show_default=False).strip().lower()

            if action == "q":
                click.echo("Triage stopped.")
                return
            elif action in ("s", ""):
                break   # move to next task
            elif action == "d":
                raw = click.prompt("Due date (e.g. tomorrow, next-friday, 2026-05-01)")
                task.due = parse_due_date(raw.strip())
                update_task(task)
                click.echo(f"  ✓  due → {task.due}")
            elif action == "p":
                pri = click.prompt("Priority (1–4)", type=click.IntRange(1, 4))
                task.priority = pri
                update_task(task)
                click.echo(f"  ✓  priority → p{task.priority}")
            elif action == "t":
                raw = click.prompt("Tags (space-separated, without @)")
                new_tags = [tag.strip() for tag in raw.split() if tag.strip()]
                task.tags = sorted(set(task.tags) | set(new_tags))
                update_task(task)
                click.echo(f"  ✓  tags → {', '.join('@' + t for t in task.tags)}")
            else:
                click.echo("  Unknown action. Use d / p / t / s / q.")

    click.echo("\nTriage complete.")


# ---------------------------------------------------------------------------
# organize
# ---------------------------------------------------------------------------

@cli.command("organize")
@click.option("--sort", "sort_by", default=None,
              type=click.Choice(["priority", "due", "title"]),
              help="Sort tasks within each section after organizing")
@click.option("--dry-run", is_flag=True, help="Preview moves/sort without writing")
@click.option("--json", "as_json", is_flag=True, help="Output result as JSON")
def cmd_organize(sort_by, dry_run, as_json):
    """Auto-assign tasks to sections based on their due dates, and optionally
    sort tasks within each section.

    \b
    Section rules:
      due <= today  →  Today
      due > today   →  Upcoming
      no due date   →  unchanged (stays in current section)

    \b
    Sort (--sort) is applied within each section after any section moves:
      --sort priority   by priority (1 first), then due date, then title
      --sort due        by due date (earliest first), then priority, then title
      --sort title      alphabetically by title

    \b
      todo organize                         # reassign sections only
      todo organize --sort priority         # reassign + sort by priority
      todo organize --sort due              # reassign + sort by due date
      todo organize --sort title --dry-run  # preview without writing
      todo organize --sort priority --json  # machine-readable output
    """
    tasks = read_tasks()
    today_str = date.today().isoformat()
    moved = []
    archived = []

    # Separate tasks manually marked done in the markdown file
    to_archive = [t for t in tasks if t.done]
    active = [t for t in tasks if not t.done]

    for task in to_archive:
        archived.append({"id": task.id, "title": task.title, "section": task.section})

    # Reassign sections for active tasks based on due dates
    for task in active:
        if is_snoozed(task) or not task.due:
            continue

        due_date = task.due.split("T")[0]
        target = "today" if due_date <= today_str else "upcoming"

        if task.section != target:
            old_section = task.section
            task.section = target
            moved.append({
                "id": task.id,
                "title": task.title,
                "from": old_section,
                "to": target,
                "due": task.due,
            })

    if sort_by:
        active = _sort_within_sections(active, sort_by)

    if not dry_run:
        for task in to_archive:
            archive_task(task)
        write_tasks(active)

    if as_json or dry_run:
        result = {"archived": archived, "moved": moved, "sorted_by": sort_by}
        click.echo(json.dumps(result, indent=2))
    else:
        if archived:
            for a in archived:
                click.echo(f"  {a['id']}  {a['title']}  → archived")
            click.echo(f"Archived {len(archived)} completed task(s).")
        if not moved:
            click.echo("All tasks are already in the right section.")
        else:
            for m in moved:
                click.echo(f"  {m['id']}  {m['title']}  {m['from']} → {m['to']}")
            click.echo(f"\nMoved {len(moved)} task(s).")
        if sort_by:
            click.echo(f"Sorted by {sort_by} within sections.")


# ---------------------------------------------------------------------------
# notify
# ---------------------------------------------------------------------------

@cli.command("notify")
@click.option("--check",      is_flag=True, help="List pending notifications and exit")
@click.option("--mark-sent",  "mark_sent_ids", multiple=True, metavar="ID",
              help="Record task IDs as notified (repeatable)")
@click.option("--reset",      "reset_id", default=None, metavar="ID",
              is_eager=False,
              help="Clear .notified entirely, or for one task ID")
@click.option("--reset-all",  is_flag=True, help="Clear all .notified state")
@click.option("--send",       "send_id", default=None, metavar="ID",
              help="Force-send notification for a task ID via the configured backend")
@click.option("--backend",    default=None, metavar="BACKEND",
              help="Override backend for --send (stdout|os|email|slack|webhook)")
@click.option("--daemon",     is_flag=True,
              help="Run as a poll loop — fires notifications via the configured backend")
@click.option("--interval",   default=None, type=int, metavar="SECONDS",
              help="Override daemon poll interval (seconds)")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def cmd_notify(check, mark_sent_ids, reset_id, reset_all, send_id,
               backend, daemon, interval, as_json):
    """Manage and deliver task notifications.

    \b
    Agent / cron usage:
      todo notify --check --json                  # list pending tasks
      todo notify --mark-sent abc123 def456       # record as sent
      todo notify --reset-all                     # re-arm all tasks
      todo notify --reset abc123                  # re-arm one task

    One-shot send via configured backend:
      todo notify --send abc123
      todo notify --send abc123 --backend slack

    Daemon (human / background):
      todo notify --daemon
      todo notify --daemon --interval 30
    """
    config = load_config()

    # ── reset ────────────────────────────────────────────────────────────
    if reset_all:
        reset_notified()
        click.echo("Cleared all notification state.")
        return

    if reset_id:
        reset_notified(reset_id)
        click.echo(f"Cleared notification state for {reset_id}.")
        return

    # ── mark-sent ────────────────────────────────────────────────────────
    if mark_sent_ids:
        mark_sent(list(mark_sent_ids))
        if as_json:
            click.echo(json.dumps({"marked_sent": list(mark_sent_ids)}, indent=2))
        else:
            for tid in mark_sent_ids:
                click.echo(f"Marked sent: {tid}")
        return

    # ── check ────────────────────────────────────────────────────────────
    if check:
        pending = get_pending()
        if as_json:
            click.echo(json.dumps(pending, indent=2))
        else:
            if not pending:
                click.echo("No pending notifications.")
                sys.exit(3)
            for p in pending:
                flag = "[OVERDUE]" if p["overdue"] else "[due soon]"
                click.echo(f"{flag}  {p['id']}  p{p['priority']}  {p['title']}  due:{p['due']}")
        return

    # ── force-send one task ───────────────────────────────────────────────
    if send_id:
        task = find_task(send_id)
        if not task:
            click.echo(f"Error: task '{send_id}' not found.", err=True)
            sys.exit(1)
        backend_name = backend or get_notification_backend_name(config)
        try:
            be = get_backend(backend_name, config)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(2)

        # Build a minimal payload for the force-send
        from datetime import datetime
        due_dt = None
        if task.due:
            try:
                due_dt = datetime.fromisoformat(task.due.split("T")[0])
            except ValueError:
                pass
        minutes_until = int((due_dt - datetime.now()).total_seconds() / 60) if due_dt else 0
        payload = {
            "id": task.id,
            "title": task.title,
            "due": task.due,
            "notify": task.notify,
            "priority": task.priority,
            "tags": task.tags,
            "overdue": due_dt < datetime.now() if due_dt else False,
            "minutes_until_due": minutes_until,
        }
        ok = be.send(payload, config)
        if ok:
            mark_sent([send_id])
            if not as_json:
                click.echo(f"Sent via {backend_name}: {send_id}")
        else:
            click.echo(f"Delivery failed via {backend_name}.", err=True)
            sys.exit(1)
        return

    # ── daemon ────────────────────────────────────────────────────────────
    if daemon:
        backend_name = get_notification_backend_name(config)
        poll_secs = interval if interval is not None else get_poll_interval(config)
        try:
            be = get_backend(backend_name, config)
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            sys.exit(2)

        click.echo(
            f"Daemon started — backend={backend_name}  interval={poll_secs}s  "
            f"(Ctrl-C to stop)"
        )
        while True:
            try:
                pending = get_pending()
                for p in pending:
                    ok = be.send(p, config)
                    if ok:
                        mark_sent([p["id"]])
                time.sleep(poll_secs)
            except KeyboardInterrupt:
                click.echo("\nDaemon stopped.")
                return
        return

    # ── no flag: print help ───────────────────────────────────────────────
    click.echo(click.get_current_context().get_help())


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

@cli.command("config")
@click.option("--init", is_flag=True,
              help="Write a default config.toml to TODO_DIR if one doesn't exist")
@click.option("--show", is_flag=True, help="Print the current merged configuration")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON (with --show)")
def cmd_config(init, show, as_json):
    """Manage the todo configuration file.

    \b
      todo config --init    # create ~/.todo/config.toml with commented defaults
      todo config --show    # print the current merged configuration
    """
    if init:
        path = write_default_config()
        click.echo(f"Config written to: {path}")
        return

    if show:
        cfg = load_config()
        if as_json:
            click.echo(json.dumps(cfg, indent=2))
        else:
            # Pretty-print sections
            for section, value in cfg.items():
                if isinstance(value, dict):
                    click.echo(f"\n[{section}]")
                    for k, v in value.items():
                        if isinstance(v, dict):
                            click.echo(f"  [{section}.{k}]")
                            for k2, v2 in v.items():
                                click.echo(f"    {k2} = {v2!r}")
                        else:
                            click.echo(f"  {k} = {v!r}")
                else:
                    click.echo(f"{section} = {value!r}")
        return

    click.echo(click.get_current_context().get_help())


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

@cli.command("search")
@click.argument("query")
@click.option("--archive", "include_archive", is_flag=True,
              help="Also search completed tasks in archive.md")
@click.option("--tag", "-t", default=None, help="Restrict to tasks with this @tag")
@click.option("--priority", "-p", type=int, default=None,
              help="Restrict to tasks with this priority")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def cmd_search(query, include_archive, tag, priority, as_json):
    """Full-text search across tasks.

    \b
      todo search "dentist"
      todo search "bug" --tag work
      todo search "report" --priority 1
      todo search "old task" --archive
      todo search "meeting" --json
    """
    from .storage import _archive_file, _ensure_dir
    from .parser import parse_line as _parse_line

    tasks = read_tasks()

    if include_archive:
        _ensure_dir()
        arc = _archive_file()
        if arc.exists():
            for line in arc.read_text().splitlines():
                t = _parse_line(line)
                if t:
                    tasks.append(t)

    # Pre-filter by tag / priority before scoring
    if tag:
        tasks = [t for t in tasks if tag in t.tags]
    if priority is not None:
        tasks = [t for t in tasks if t.priority == priority]

    results = search_tasks(query, tasks)

    if as_json:
        click.echo(json.dumps(
            [{"score": r.score,
              "matched_fields": r.matched_fields,
              "task": r.task.to_dict()} for r in results],
            indent=2,
        ))
        return

    if not results:
        click.echo(f"No tasks matched '{query}'.")
        sys.exit(3)

    config = load_config()
    date_fmt = get_date_format(config)
    for r in results:
        matched = ", ".join(r.matched_fields)
        click.echo(f"[score:{r.score} {matched}]  {_task_row(r.task, date_fmt)}")


# ---------------------------------------------------------------------------
# completions
# ---------------------------------------------------------------------------

@cli.command("completions")
@click.option(
    "--shell",
    type=click.Choice(["bash", "zsh", "fish"]),
    default=None,
    help="Target shell (auto-detected from $SHELL if omitted)",
)
@click.option("--install", "do_install", is_flag=True,
              help="Write the completion script to the standard location")
def cmd_completions(shell, do_install):
    """Generate or install shell tab-completions.

    \b
    Print to stdout (then source manually):
      todo completions --shell bash
      todo completions --shell zsh
      todo completions --shell fish

    Auto-detect shell and install:
      todo completions --install
      todo completions --shell zsh --install
    """
    resolved = shell or detect_shell()

    if do_install:
        ok, msg = install_completions(resolved)
        click.echo(msg)
        if not ok:
            sys.exit(1)
        return

    script = get_script(resolved)
    click.echo(script, nl=False)
