# ¯\(ツ)/¯mdone — Complete Reference

**Version 1.0.0**

> **Primary audience**: AI agents integrating with ¯\(ツ)/¯mdone.  
> **Also covers**: Human setup, configuration, and day-to-day usage.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Installation](#2-installation)
3. [Sections](#3-sections)
4. [Storage Layout](#4-storage-layout)
5. [Task Line Schema](#5-task-line-schema)
6. [Exit Codes](#6-exit-codes)
7. [Commands Reference](#7-commands-reference)
   - [add](#71-add)
   - [list / ls](#72-list--ls)
   - [done](#73-done)
   - [delete / rm](#74-delete--rm)
   - [edit](#75-edit)
   - [snooze](#76-snooze)
   - [recap](#77-recap)
   - [triage](#78-triage)
   - [organize](#79-organize)
   - [notify](#710-notify)
   - [config](#711-config)
   - [search](#712-search)
   - [completions](#713-completions)
8. [Date Parsing](#8-date-parsing)
9. [Recurrence Engine](#9-recurrence-engine)
10. [NLP Mode](#10-nlp-mode)
11. [Notification System](#11-notification-system)
12. [Search Algorithm](#12-search-algorithm)
13. [Configuration File](#13-configuration-file)
14. [Agent Integration Guide](#14-agent-integration-guide)
15. [Human User Guide](#15-human-user-guide)

---

## 1. Overview

¯\(ツ)/¯mdone is a **Markdown-native**, **AI-agent-friendly** CLI todo manager. Tasks are stored as human-readable Markdown checkboxes in `~/.todo/tasks.md`, organised under named section headers. Every command that mutates state supports `--dry-run` and `--json` flags for safe, machine-readable operation.

Key design principles:

- **Sections**: tasks are grouped under `## Inbox`, `## Today`, `## Upcoming`, `## Someday`, and `## Waiting` — auto-assigned from due dates, overridable at any time
- **Pull model for agents**: no background daemon required — agents call `mdone notify --check --json`, then dispatch notifications themselves
- **Markdown as source of truth**: files are hand-editable; the CLI reads and writes the same format
- **Composable**: every output mode has a `--json` flag returning stable, versioned JSON; `--json-pretty` adds indentation for human inspection
- **Zero network calls at rest**: all data is local; external services (email, Slack, webhooks) are only contacted on explicit notification dispatch

---

## 2. Installation

### Standard install (recommended)

```bash
git clone <repo>
cd mdone
pip install .
```

This installs `mdone` as a global command via the `[project.scripts]` entry point in `pyproject.toml`.

### Editable install (for development)

```bash
pip install -e .
```

Changes to source files take effect immediately without reinstalling.

### PATH note (macOS user installs)

If pip installs to the user site directory (common on macOS system Python), add it to `PATH`:

```bash
# Add to ~/.zshrc or ~/.bash_profile
export PATH="$HOME/Library/Python/3.9/bin:$PATH"
```

Then reload: `source ~/.zshrc`

### Install dev dependencies

```bash
pip install -e ".[dev]"   # includes pytest
```

### Verify

```bash
mdone --help
mdone --version   # prints: ¯\(ツ)/¯mdone  1.0.0
```

### Package files

| File             | Purpose                                                  |
|------------------|----------------------------------------------------------|
| `pyproject.toml` | Package metadata, dependencies, `mdone` entry point      |
| `setup.py`       | Minimal shim for editable installs with older pip (<22)  |

### Runtime dependencies

```
click>=8.0
dateparser>=1.1
tomli>=2.0; python_version < "3.11"
```

`dateparser` is optional at runtime: if not installed, `--natural` mode gracefully degrades (date extraction is skipped; title/tags/priority still work).

### Environment variables

| Variable   | Description                                           | Default    |
|------------|-------------------------------------------------------|------------|
| `TODO_DIR` | Directory for all mdone files (tasks.md, config.toml)  | `~/.todo/` |

Set `TODO_DIR` to isolate test runs or support multiple mdone lists:

```bash
TODO_DIR=/tmp/test-mdone mdone add "Test task"
```

---

## 3. Sections

Tasks are grouped under five sections that reflect their status and intent. Sections are stored as `## Header` lines in `tasks.md` and are visible when you open the file in any text editor.

| Section    | Purpose                                                                 |
|------------|-------------------------------------------------------------------------|
| `inbox`    | Newly captured tasks — not yet scheduled or categorised (default)       |
| `today`    | Tasks due today or overdue — your active focus list                     |
| `upcoming` | Tasks with a future due date                                            |
| `someday`  | Parked ideas with no deadline — review periodically                     |
| `waiting`  | Tasks blocked on someone or something external                          |

### Auto-assignment

When a task is added, its section is inferred from its due date unless `--section` is specified:

| Due date          | Auto-assigned section |
|-------------------|-----------------------|
| Today or earlier  | `today`               |
| Future date       | `upcoming`            |
| None              | `inbox`               |

### Moving tasks between sections

```bash
# Explicitly at add time
mdone add "Parked idea" --section someday
mdone add "Waiting on legal" --section waiting

# Move an existing task
mdone edit abc12345 --set section:someday

# Auto-reassign all tasks based on due dates
mdone organize
```

### `organize` — bulk auto-reassignment and sorting

`mdone organize` applies the auto-assignment rules to every existing task that has a due date:
- `due <= today` → **today**
- `due > today` → **upcoming**
- no due date → **unchanged** (stays where it is)

`--sort` physically reorders tasks within their sections in `tasks.md`:

| Value      | Order within each section                                 |
|------------|-----------------------------------------------------------|
| `priority` | Priority 1 first, then due date (earliest), then title    |
| `due`      | Earliest due date first, then priority, then title        |
| `title`    | Alphabetical by title                                     |

Run `mdone organize --dry-run` to preview moves without writing.

---

## 4. Storage Layout

All files live inside `TODO_DIR` (default `~/.todo/`).

```
~/.todo/
├── tasks.md       # Active tasks, grouped under section headers
├── archive.md     # Completed tasks (append-only, flat)
├── .notified      # Notification deduplication state (tab-separated)
└── config.toml    # Optional configuration (human-editable TOML)
```

### tasks.md

Tasks are written one per line under `## Section` headers. All five section headers are always present (even when a section is empty), making the file self-documenting.

```markdown
## Inbox
- [ ] Call dentist id:ua7zeaxt

## Today
- [ ] Fix login bug @work due:2026-04-14 priority:1 id:6fs53liw

## Upcoming
- [ ] Q2 planning @work due:2026-06-01 priority:2 id:4bvvbdy5

## Someday
- [ ] Learn guitar id:mu473bvw

## Waiting
- [ ] Waiting on Bob's review id:vfxgb30r
```

**Reading rules**:
- Each task inherits the section of the nearest preceding `## Header`
- Tasks that appear before any header default to `inbox`
- Unrecognised headers (e.g. `## Archive`) do not change the current section
- Non-task lines (blank lines, comments) are silently skipped

**Writing rules**:
- `write_tasks()` always emits all five section headers in order
- Tasks are placed under their `task.section` header
- Tasks with an unknown section value fall back to `inbox`

### archive.md

Same per-line format as `tasks.md`, but flat (no section headers). Tasks are appended (never removed) when completed via `done`.

### .notified

Tab-separated file, one record per line: `task_id<TAB>YYYY-MM-DDTHH:MM`

```
abc12345	2026-04-14T08:30
def67890	2026-04-13T09:01
```

Lines starting with `#` are treated as comments and ignored.

### config.toml

TOML format. Created by `mdone config --init`. See [Configuration File](#13-configuration-file).

---

## 5. Task Line Schema

The full task mini-syntax (section is **not** part of the line — it is derived from the file position):

```
- [<status>] <title> [<fields>...] id:<id>
```

| Component                  | Format                                   | Notes                                         |
|----------------------------|------------------------------------------|-----------------------------------------------|
| `<status>`                 | ` ` (space) or `x`                       | Space = open, `x` = done                      |
| `<title>`                  | Free text                                | Required. May contain spaces.                 |
| `@<tag>`                   | `@word`                                  | Multiple allowed. `(?:^|\s)@(\w+)` pattern.   |
| `+<context>`               | `+word`                                  | Multiple allowed. `(?:^|\s)\+(\w+)` pattern.  |
| `due:<date>`               | ISO 8601 date or datetime                | `due:2026-04-15` or `due:2026-04-15T09:00`    |
| `priority:<n>`             | Integer 1–4                              | 1=urgent, 2=high, 3=medium, 4=none (default)  |
| `recur:<rule>`             | `daily` / `weekly` / `monthly`           | Spawns next occurrence when task is completed |
| `notify:<lead>`            | `30m` / `2h` / `1d`                      | Lead time before due for notifications        |
| `snooze:<dt>`              | `YYYY-MM-DDTHH:MM`                       | Hidden from list until this time              |
| `idempotency_key:<key>`    | Any non-whitespace string                | Stable caller key for exact deduplication     |
| `id:<id>`                  | 8-char alphanumeric                      | Auto-generated; always present after `add`    |

**Example — full mini-syntax**:

```
- [ ] Weekly report @work due:2026-04-18 priority:2 recur:weekly notify:2h id:ab3xy901
```

**Example — minimal**:

```
- [ ] Buy oat milk id:zz9kl2mn
```

### ID format

IDs are 8-character strings using lowercase letters and digits (`[a-z0-9]`), generated with `secrets.choice()` for cryptographic randomness. They are globally unique within a task list.

### JSON envelope

Every `--json` response is wrapped in a versioned envelope:

```json
{"schema_version": 1, "data": <payload>}
```

`schema_version` is a monotonically increasing integer. Agents should assert `schema_version == 1` and read `data` for the actual payload. The envelope never changes shape; only `data` varies by command.

`--json` outputs compact (single-line) JSON. `--json-pretty` outputs the same envelope indented for human readability.

### Task JSON shape

`to_dict()` returns all fields including `section`. This object appears as the `data` payload (or inside a `data` array) in command responses:

```json
{
  "id":       "ab3xy901",
  "title":    "Weekly report",
  "done":     false,
  "tags":     ["work"],
  "contexts": [],
  "due":      "2026-04-18",
  "priority": 2,
  "recur":            "weekly",
  "notify":           "2h",
  "snooze":           null,
  "section":          "upcoming",
  "idempotency_key":  null
}
```

All fields are always present. `null` indicates unset optional fields.

---

## 6. Exit Codes

| Code | Meaning                                                    |
|------|------------------------------------------------------------|
| `0`  | Success                                                    |
| `1`  | Task not found                                             |
| `2`  | Parse / input error (invalid field, format)                |
| `3`  | No tasks matched the filter or query                       |
| `4`  | Duplicate found (`--dedup` without `--force`)              |

---

## 7. Commands Reference

### 7.1 `add`

Add a new task.

```
mdone add [OPTIONS] TASK_STRING
```

**Options**

| Flag                          | Description                                                           |
|-------------------------------|-----------------------------------------------------------------------|
| `--natural`, `-n`             | Interpret TASK_STRING as plain English (NLP mode)                     |
| `--section`, `-s SECTION`     | Override auto-assigned section (`inbox`/`today`/`upcoming`/`someday`/`waiting`) |
| `--dry-run`                   | Output parsed task as JSON without saving                             |
| `--json`                      | Output created task as compact JSON after saving                      |
| `--json-pretty`               | Output as indented JSON (for humans; implies `--json`)                |

**Section assignment**

Without `--section`, the section is inferred from the due date:
- `due <= today` → `today`
- `due > today` → `upcoming`
- no due date → `inbox`

Use `--section` to override:

```bash
mdone add "Parked idea" --section someday
mdone add "Waiting on approval due:2099-01-01" --section waiting
```

**Mini-syntax mode (default)**

TASK_STRING is parsed for inline fields using the [task schema](#5-task-line-schema):

```bash
mdone add "Buy milk @shopping due:tomorrow priority:2"
mdone add "Stand-up @work due:2026-04-15T09:00 recur:daily notify:30m"
mdone add "Read chapter 3 @personal priority:3" --json
mdone add "Someday idea" --section someday
```

**NLP mode (`--natural`)**

TASK_STRING is interpreted as free English text. Extracts title, due date, tags, and priority:

```bash
mdone add -n "remind me to call Alice next Friday at 3pm"
mdone add -n "urgent: fix the login bug tomorrow"
mdone add -n "dentist appointment on May 5th"
mdone add -n "buy groceries" --section someday --dry-run
```

**Config defaults applied on `add`**

If `config.toml` defines defaults, they are applied when not already set by the task string:

- `tags.default_tags` — appended to task tags
- `general.default_priority` — used if task has no explicit priority
- `notifications.default_notify` — used if task has no `notify:` field

**`--dry-run` output** (always JSON regardless of `--json` flag):

```json
{"schema_version":1,"data":{"id":"ab3xy901","title":"Buy milk","done":false,"tags":["shopping"],"contexts":[],"due":"2026-04-15","priority":2,"recur":null,"notify":null,"snooze":null,"section":"today"}}
```

**`--json` output**: same `data` shape, written to stdout after the task is saved. **`--json-pretty`** adds indentation to either.

**Text output**:

```
Added [today]: ab3xy901  Buy milk
```

The section name is shown in brackets so agents can confirm placement.

---

### 7.2 `list` / `ls`

List tasks with optional filters.

```
mdone list [OPTIONS]
mdone ls   [OPTIONS]
```

**Options**

| Flag                          | Description                                      |
|-------------------------------|--------------------------------------------------|
| `--tag`, `-t TAG`             | Filter by @tag                                   |
| `--priority`, `-p N`          | Filter by priority (1–4)                         |
| `--due DATE`                  | Filter by due date (ISO, relative, or `today`)   |
| `--overdue`                   | Show tasks past their due date                   |
| `--done`                      | Show completed tasks instead of open ones        |
| `--all`                       | Include snoozed tasks (hidden by default)        |
| `--section`, `-s SECTION`     | Filter to one section; output is flat (no header)|
| `--sort FIELD`                | Sort output by `priority` (default), `due`, or `title` — display only, does not reorder `tasks.md` |
| `--json`                      | Output as compact JSON                           |
| `--json-pretty`               | Output as indented JSON (for humans; implies `--json`) |

**Behavior**

- Open (incomplete) tasks are shown by default; `--done` shows completed ones
- Snoozed tasks are hidden unless `--all` is passed
- Without `--section`: text output groups tasks under section headers (empty sections are hidden)
- With `--section`: text output is flat (no header line); acts as a precise filter
- `--json` always returns a flat array with `section` included in each task object
- `--sort` affects display order only — to permanently reorder `tasks.md` use `mdone organize --sort`

**Text output (default — grouped by section)**:

```
## Inbox (1)
────────────────────────────────────────
[ ] ua7zeaxt      Call dentist

## Today (1)
────────────────────────────────────────
[ ] 6fs53liw  p1  Fix login bug @work  due:2026-04-14

## Upcoming (1)
────────────────────────────────────────
[ ] 4bvvbdy5  p2  Q2 planning @work  due:2026-06-01
```

Only non-empty sections are shown. Sort order applies within each section.

**Text output (`--section today` — flat)**:

```
[ ] 6fs53liw  p1  Fix login bug @work  due:2026-04-14
```

**`--json` output**:

```json
{"schema_version":1,"data":[{"id":"6fs53liw","title":"Fix login bug","section":"today",...}]}
```

`data` is always an array. Returns `{"schema_version":1,"data":[]}` (exit 0) with `--json` when no tasks match. Without `--json`, exits with code `3`.

---

### 7.3 `done`

Mark one or more tasks complete. Recurring tasks automatically spawn their next occurrence.

```
mdone done [OPTIONS] TASK_ID [TASK_ID ...]
```

**Options**

| Flag        | Description                                            |
|-------------|--------------------------------------------------------|
| `--dry-run`     | Preview what would be archived/spawned without writing |
| `--json`        | Output results as compact JSON                         |
| `--json-pretty` | Output as indented JSON (for humans; implies `--json`) |

**Behavior**

1. Task is marked `done=True` and appended to `archive.md`
2. Task is removed from `tasks.md`
3. If `recur:` is set, a new task is spawned with a fresh ID, the next due date, `snooze=null`, and the same section as the completed task

Multiple IDs can be passed in a single call:

```bash
mdone done abc12345 def67890 ghi11111
```

**`--json` output** (always emitted with `--dry-run`):

```json
{"schema_version":1,"data":[{"completed":{"id":"abc12345","title":"Weekly report","section":"today","done":false,...},"spawned":{"id":"xyz99887","title":"Weekly report","section":"today","due":"2026-04-25",...},"dry_run":false}]}
```

`data` is an array with one entry per task ID passed. `spawned` is `null` for non-recurring tasks.

**Text output**:

```
Done: abc12345  Weekly report
  ↻  Next: xyz99887  Weekly report  due:2026-04-25
```

---

### 7.4 `delete` / `rm`

Delete a task permanently (no archive).

```
mdone delete [OPTIONS] TASK_ID
mdone rm     [OPTIONS] TASK_ID
```

**Options**

| Flag        | Description                      |
|-------------|----------------------------------|
| `--dry-run`     | Preview deletion without writing                       |
| `--json`        | Output result as compact JSON                          |
| `--json-pretty` | Output as indented JSON (for humans; implies `--json`) |

**`--json` output**:

```json
{"schema_version":1,"data":{"deleted":"abc12345","task":{"id":"abc12345","title":"...","section":"today",...},"dry_run":false}}
```

**Text output**: `Deleted: abc12345`

---

### 7.5 `edit`

Edit a task — replace it entirely or update individual fields.

```
mdone edit [OPTIONS] TASK_ID [TASK_STRING]
```

**Options**

| Flag                 | Description                                                      |
|----------------------|------------------------------------------------------------------|
| `TASK_STRING`        | Replace the full task definition (preserves id, done, section)   |
| `--set FIELD:VALUE`  | Set a specific field. Repeatable.                                |
| `--dry-run`          | Preview the result without saving                                |
| `--json`             | Output updated task as compact JSON                              |
| `--json-pretty`      | Output as indented JSON (for humans; implies `--json`)           |

**Settable fields** via `--set`:

| Field      | Accepted values                                                        |
|------------|------------------------------------------------------------------------|
| `title`    | Free text                                                              |
| `due`      | Any value accepted by [date parser](#8-date-parsing)                   |
| `priority` | `1`–`4`                                                                |
| `recur`    | `daily` / `weekly` / `monthly`                                         |
| `notify`   | `30m` / `2h` / `1d`                                                    |
| `snooze`   | `30m` / `2h` / `1d` (converted to absolute datetime)                   |
| `section`  | `inbox` / `today` / `upcoming` / `someday` / `waiting`                 |

**Examples**:

```bash
# Replace entire task (section is preserved)
mdone edit abc12345 "New title @newtag due:next-monday"

# Update individual fields
mdone edit abc12345 --set priority:1 --set due:tomorrow

# Move to a different section
mdone edit abc12345 --set section:waiting

# Multiple fields + preview
mdone edit abc12345 --set notify:2h --set recur:weekly --dry-run

# Agent: get JSON back
mdone edit abc12345 --set priority:2 --json
```

**`--json` output**: `{"schema_version":1,"data":<task-object>}` — same task shape as `add --json`, includes `section`.

Exit code `2` if an unknown field or section value is passed to `--set`.

---

### 7.6 `snooze`

Hide a task from the default list view until a given time.

```
mdone snooze [OPTIONS] TASK_ID [DURATION]
```

**Options**

| Flag        | Description                                 |
|-------------|---------------------------------------------|
| `DURATION`      | `30m` / `2h` / `1d` / `YYYY-MM-DDTHH:MM`              |
| `--clear`       | Remove the snooze from a task                          |
| `--dry-run`     | Preview without saving                                 |
| `--json`        | Output updated task as compact JSON                    |
| `--json-pretty` | Output as indented JSON (for humans; implies `--json`) |

**Examples**:

```bash
mdone snooze abc12345 30m
mdone snooze abc12345 2h
mdone snooze abc12345 1d
mdone snooze abc12345 2026-04-20T09:00
mdone snooze abc12345 --clear
mdone snooze abc12345 2h --dry-run
```

Snoozed tasks are hidden from `list` and `recap` unless `--all` is passed. They are still reassigned by `organize` if they have a due date.

**`--json` output**: `{"schema_version":1,"data":<task-object>}` with `"snooze": "2026-04-15T10:30"` (or `null` after `--clear`).

---

### 7.7 `recap`

Summarise overdue tasks and what's due today (or this week).

```
mdone recap [OPTIONS]
```

**Options**

| Flag     | Description                                      |
|----------|--------------------------------------------------|
| `--week`        | Show full 7-day lookahead instead of today only        |
| `--json`        | Output as compact JSON                                 |
| `--json-pretty` | Output as indented JSON (for humans; implies `--json`) |

**`--json` output** (daily recap):

```json
{"schema_version":1,"data":{"overdue":[{"id":"...","section":"today",...}],"today":[{"id":"...","section":"today",...}]}}
```

**`--json` output** (weekly `--week`):

```json
{"schema_version":1,"data":{"overdue":[...],"upcoming":[...],"no_due_date":[...]}}
```

Snoozed tasks are excluded from all recap views.

**Text output**:

```
OVERDUE (2)
────────────────────────────────────────
[ ] abc12345  p1  Fix login bug @work  due:2026-04-12

TODAY — Wed Apr 15 (1)
────────────────────────────────────────
[ ] def67890  p2  Weekly report @work  due:2026-04-15
```

---

### 7.8 `triage`

Assign due dates and priorities to unscheduled tasks.

```
mdone triage [OPTIONS]
```

A task needs triage when it has **no due date AND no priority set** (priority == 4).

**Options**

| Flag     | Description                                                  |
|----------|--------------------------------------------------------------|
| `--json`        | Non-interactive: print untriaged tasks as compact JSON and exit |
| `--json-pretty` | Output as indented JSON (for humans; implies `--json`)          |

**Agent usage**: `mdone triage --json` returns an array of tasks that need triage. The agent can then call `mdone edit <id> --set due:<date>` or `mdone edit <id> --set priority:<n>` for each. After assigning due dates, run `mdone organize --sort` to move tasks to the right sections and sort within them.

```bash
# Get tasks needing triage
mdone triage --json

# Assign due date and priority
mdone edit abc12345 --set due:next-friday --set priority:2

# Move to correct section and sort by priority
mdone organize --sort priority
```

**`--json` output**:

```json
{"schema_version":1,"data":[{"id":"abc12345","title":"Unscheduled task","due":null,"priority":4,"section":"inbox",...}]}
```

**Interactive mode** (human): shows each task and offers prompts:

```
──────────────────────────────────────────────────────
 1/3  [ ] abc12345    Unscheduled task @personal
──────────────────────────────────────────────────────
  [d]ue  [p]riority  [t]ag  [s]kip  [q]uit
>
```

---

### 7.9 `organize`

Auto-assign tasks to sections based on their due dates, and optionally sort tasks within each section.

```
mdone organize [OPTIONS]
```

**Options**

| Flag                          | Description                                                           |
|-------------------------------|-----------------------------------------------------------------------|
| `--sort priority\|due\|title` | Sort tasks within each section after organizing                       |
| `--dry-run`                   | Preview moves/sort without writing                                    |
| `--json`                      | Output result as compact JSON                                         |
| `--json-pretty`               | Output as indented JSON (for humans; implies `--json`)                |

**Section assignment rules**:

| Condition       | Target section |
|-----------------|----------------|
| `due <= today`  | `today`        |
| `due > today`   | `upcoming`     |
| no due date     | unchanged      |

Tasks in `someday` or `waiting` are also reassigned if they have a due date.

**Sort order** (`--sort`): applied within each section after any section moves. Tasks remain inside their section — only the order within each section changes.

| Value      | Order within each section                              |
|------------|--------------------------------------------------------|
| `priority` | Priority 1 first, then due date (earliest), then title |
| `due`      | Earliest due date first, then priority, then title     |
| `title`    | Alphabetical by title                                  |

**Examples**:

```bash
# Reassign sections only
mdone organize

# Reassign + sort by priority
mdone organize --sort priority

# Reassign + sort by due date
mdone organize --sort due

# Sort alphabetically, preview without writing
mdone organize --sort title --dry-run

# Machine-readable output
mdone organize --sort priority --json
```

**`--json` output**:

```json
{"schema_version":1,"data":{"archived":[],"moved":[{"id":"abc12345","title":"Old task","from":"inbox","to":"today","due":"2020-01-01"}],"sorted_by":"priority"}}
```

`moved` is an empty array when no tasks needed reassignment. `sorted_by` is `null` when `--sort` is not specified. `archived` lists any tasks that were marked done directly in `tasks.md` and moved to `archive.md`.

**Text output**:

```
  abc12345  Old task  inbox → today
  def67890  Future task  inbox → upcoming

Moved 2 task(s).
Sorted by priority within sections.
```

Or, when nothing to move:

```
All tasks are already in the right section.
Sorted by due within sections.
```

---

### 7.10 `notify`

Manage and deliver task notifications.

```
mdone notify [OPTIONS]
```

**Options**

| Flag                   | Description                                                           |
|------------------------|-----------------------------------------------------------------------|
| `--check`              | List pending notifications and exit                                   |
| `--mark-sent ID`       | Record task ID as notified (repeatable)                               |
| `--reset ID`           | Clear notification state for one task ID                              |
| `--reset-all`          | Clear all notification state                                          |
| `--send ID`            | Force-send notification for a task via the configured backend         |
| `--backend BACKEND`    | Override backend for `--send` (`stdout`/`os`/`email`/`slack`/`webhook`) |
| `--daemon`             | Run as a poll loop                                                    |
| `--interval SECONDS`   | Override daemon poll interval                                         |
| `--json`               | Output as compact JSON                                                |
| `--json-pretty`        | Output as indented JSON (for humans; implies `--json`)                |

**`--check --json` output** (core agent integration point):

```json
{"schema_version":1,"data":[{"id":"abc12345","title":"Fix login bug","due":"2026-04-15T09:00","notify":"1h","priority":1,"tags":["work"],"overdue":false,"minutes_until_due":45}]}
```

`data` is always an array. Returns `{"schema_version":1,"data":[]}` when no notifications are pending (exit 0).

**`--mark-sent --json` output**:

```json
{"schema_version":1,"data":{"marked_sent":["abc12345","def67890"]}}
```

See the [Agent Integration Guide](#14-agent-integration-guide) for the recommended notification workflow.

---

### 7.11 `config`

Manage the mdone configuration file.

```
mdone config [OPTIONS]
```

**Options**

| Flag     | Description                                               |
|----------|-----------------------------------------------------------|
| `--init`        | Write a default config.toml to TODO_DIR (no-op if exists) |
| `--show`        | Print the current merged configuration                    |
| `--json`        | Output current config as compact JSON (with `--show`)     |
| `--json-pretty` | Output as indented JSON (for humans; implies `--json`)    |

```bash
# Create config with commented defaults
mdone config --init

# View effective config (user overrides merged with defaults)
mdone config --show

# Machine-readable config dump
mdone config --show --json
```

**`--show --json` output**:

```json
{"schema_version":1,"data":{"general":{"date_format":"%Y-%m-%d","default_priority":4},"tags":{"default_tags":[]},"notifications":{"backend":"stdout","default_notify":"","poll_interval":60,"email":{},"slack":{},"webhook":{}}}}
```

---

### 7.12 `search`

Full-text search across tasks.

```
mdone search [OPTIONS] QUERY
```

**Options**

| Flag                  | Description                                      |
|-----------------------|--------------------------------------------------|
| `--archive`           | Also search completed tasks in archive.md              |
| `--tag`, `-t TAG`     | Restrict results to tasks with this @tag               |
| `--priority`, `-p N`  | Restrict results to tasks with this priority           |
| `--json`              | Output results as compact JSON                         |
| `--json-pretty`       | Output as indented JSON (for humans; implies `--json`) |

**`--json` output**:

```json
{"schema_version":1,"data":[{"score":6,"matched_fields":["title","tags"],"task":{"id":"...","title":"...","section":"today",...}}]}
```

Results are sorted by descending score, then alphabetically by title. Exit code `3` with no `--json` if no results.

---

### 7.13 `completions`

Generate or install shell tab-completions.

```
mdone completions [OPTIONS]
```

**Options**

| Flag                         | Description                                             |
|------------------------------|---------------------------------------------------------|
| `--shell bash\|zsh\|fish`    | Target shell (auto-detected from `$SHELL` if omitted)   |
| `--install`                  | Write the completion script to the standard location    |

**Manual installation**:

```bash
# Bash
mdone completions --shell bash >> ~/.bash_completion
source ~/.bash_completion

# Zsh (fpath method)
mdone completions --shell zsh > ~/.zsh/completions/_mdone
# ensure ~/.zsh/completions is in $fpath

# Fish
mdone completions --shell fish > ~/.config/fish/completions/mdone.fish
```

**Auto-install** (detects shell from `$SHELL`):

```bash
mdone completions --install
mdone completions --shell zsh --install
```

Standard install paths:

| Shell | Path                                    |
|-------|-----------------------------------------|
| bash  | `~/.bash_completion`                    |
| zsh   | `~/.zsh/completions/_mdone`              |
| fish  | `~/.config/fish/completions/mdone.fish`  |

---

## 8. Date Parsing

The `parse_due_date(value)` function normalizes all date inputs to ISO 8601 (`YYYY-MM-DD` or `YYYY-MM-DDTHH:MM`).

### Accepted formats

| Input                      | Resolves to                                   |
|----------------------------|-----------------------------------------------|
| `today`                    | Current date                                  |
| `tomorrow`                 | Current date + 1 day                          |
| `next-friday`              | Next occurrence of Friday                     |
| `in-3-days`                | Current date + 3 days                         |
| `in-2-weeks`               | Current date + 14 days                        |
| `in-1-month`               | Current date + 1 month (end-of-month clamped) |
| `2026-04-15`               | `2026-04-15` (stored as-is)                   |
| `2026-04-15T09:00`         | `2026-04-15T09:00` (datetime stored as-is)    |
| Any above via `--set due:` | Same rules                                    |

Month arithmetic uses end-of-month clamping: January 31 + 1 month = February 28/29.

### Snooze duration parsing

`parse_snooze_duration(value)` converts relative durations to an absolute `YYYY-MM-DDTHH:MM` string:

| Input              | Resolves to                      |
|--------------------|----------------------------------|
| `30m`              | now + 30 minutes                 |
| `2h`               | now + 2 hours                    |
| `1d`               | now + 1 day                      |
| `YYYY-MM-DDTHH:MM` | stored as-is (absolute datetime) |

---

## 9. Recurrence Engine

When a task with `recur:` is marked done, `spawn_next_occurrence(task)` creates a new task with:

- Fresh 8-character ID
- Next due date calculated from the original due date
- All other fields copied (title, tags, contexts, priority, notify, recur, **section**)
- `snooze` reset to `null`

The spawned task inherits the parent's section. Run `mdone organize --sort <field>` afterwards to auto-reassign based on the new due date and re-sort within sections.

### Recurrence rules

| Rule      | Next due date                           |
|-----------|-----------------------------------------|
| `daily`   | `due + 1 day`                           |
| `weekly`  | `due + 7 days`                          |
| `monthly` | `due + 1 month` (end-of-month clamped)  |

If the task has no `due:` field, `spawn_next_occurrence` returns `None` (no recurrence without a due date).

### done + recurrence JSON

```bash
mdone done abc12345 --json
```

```json
{"schema_version":1,"data":[{"completed":{"id":"abc12345","title":"Weekly report","section":"today","due":"2026-04-18","recur":"weekly",...},"spawned":{"id":"xyz99887","title":"Weekly report","section":"today","due":"2026-04-25","recur":"weekly",...},"dry_run":false}]}
```

---

## 10. NLP Mode

`mdone add --natural TEXT` runs the full NLP pipeline:

### Pipeline stages

1. **Filler stripping** — removes common preambles:
   - `remind me to`, `don't forget to`, `i need to`, `please`, `make sure to`, `remember to`, `i should`, `i must`, `i have to`, `can you`

2. **Priority inference** — scans lowercased text for keywords:
   - Priority 1 (urgent): `urgent`, `asap`, `immediately`, `critical`, `emergency`
   - Priority 2 (high): `important`, `high priority`, `must`, `need to`, `required`
   - Priority 3 (medium): `should`, `medium`, `normal`
   - Priority 4 (none): `someday`, `maybe`, `eventually`, `low priority`, `whenever`

3. **Tag inference** — keyword-to-tag mapping:
   - `@health`: gym, workout, exercise, doctor, dentist, medical, health, appointment
   - `@work`: meeting, standup, sprint, deadline, report, client, email, office, project, review, deploy
   - `@shopping`: buy, shop, purchase, grocery, groceries, order, amazon, store
   - `@finance`: pay, invoice, bill, bank, expense, budget, money, tax
   - `@home`: clean, fix, repair, maintenance, house, home, apartment
   - `@personal`: call, text, birthday, friend, family, personal

4. **Date extraction** — uses `dateparser.search.search_dates()` to extract date expressions; picks the one furthest in the future

5. **Title cleanup** — strips dangling prepositions (`on`, `by`, `at`, `in`, `for`, `to`, `the` at end of string), removes priority prefix keywords (`urgent:`, `important:` etc.), sentence-cases the result

After the NLP pipeline runs, section is auto-assigned from the extracted due date (same rules as `add`).

### Graceful degradation

If `dateparser` is not installed, stages 1–3 and 5 still run; only date extraction is skipped.

### Example

```bash
mdone add -n "urgent: fix the login bug tomorrow" --dry-run
```

```json
{"schema_version":1,"data":{"id":"ab3xy901","title":"Fix the login bug","done":false,"tags":["work"],"contexts":[],"due":"2026-04-14","priority":1,"recur":null,"notify":null,"snooze":null,"section":"today"}}
```

---

## 11. Notification System

### Architecture

¯\(ツ)/¯mdone uses a **pull model** designed for agents and cron jobs:

```
┌─────────────────────────────────────────────────────────────┐
│                     Agent / Cron Job                        │
│                                                             │
│  1. mdone notify --check --json   →  pending[] payload       │
│  2. For each item: dispatch via own channel (email/Slack/…) │
│  3. mdone notify --mark-sent <id> [<id> …]                   │
└─────────────────────────────────────────────────────────────┘
```

No daemon or background process is required for agent use.

### Pending detection logic

A task is included in `--check` results when **all** of the following hold:

1. Not done (`done == false`)
2. Not snoozed (current time >= `snooze` or `snooze` is null)
3. Has a `due:` field
4. Not already in `.notified`
5. Notification window is open:
   - If `notify:` is set: `now >= due - lead_time`
   - If `notify:` is not set: task is overdue (`now > due`)

### Payload fields

```json
{
  "id":               "abc12345",
  "title":            "Fix login bug",
  "due":              "2026-04-15T09:00",
  "notify":           "1h",
  "priority":         1,
  "tags":             ["work"],
  "overdue":          false,
  "minutes_until_due": 45
}
```

`minutes_until_due` is negative for overdue tasks.

Results are sorted: overdue first, then by ascending due datetime, then by priority.

### Notification backends

Configure via `notifications.backend` in `config.toml`:

| Backend   | Description                                  | Config section            |
|-----------|----------------------------------------------|---------------------------|
| `stdout`  | Print JSON payload to stdout (default)       | none                      |
| `os`      | Native OS notification (macOS/Linux/Windows) | none                      |
| `email`   | SMTP email                                   | `[notifications.email]`   |
| `slack`   | Slack Incoming Webhook                       | `[notifications.slack]`   |
| `webhook` | Generic HTTP POST                            | `[notifications.webhook]` |

#### stdout backend

Prints the JSON payload to stdout. Returns `true` always. Default for agents.

#### OS backend

- **macOS**: `osascript -e 'display notification ...'`
- **Linux**: `notify-send`
- **Windows**: `win10toast`

#### Email backend (SMTP)

Config keys in `[notifications.email]`:

| Key            | Description                               | Example             |
|----------------|-------------------------------------------|---------------------|
| `smtp_host`    | SMTP server hostname                      | `smtp.gmail.com`    |
| `smtp_port`    | SMTP port (default 587)                   | `587`               |
| `from`         | From address                              | `todo@example.com`  |
| `to`           | Recipient address                         | `you@example.com`   |
| `username_env` | **Name** of env var holding SMTP username | `SMTP_USER`         |
| `password_env` | **Name** of env var holding SMTP password | `SMTP_PASSWORD`     |

Credentials are read from environment variables at delivery time (never stored in config).

```toml
[notifications.email]
smtp_host    = "smtp.gmail.com"
smtp_port    = 587
from         = "todo-agent@example.com"
to           = "you@example.com"
username_env = "SMTP_USER"
password_env = "SMTP_PASSWORD"
```

#### Slack backend (Incoming Webhook)

Config key in `[notifications.slack]`:

| Key               | Description                                       |
|-------------------|---------------------------------------------------|
| `webhook_url_env` | **Name** of env var holding the Slack webhook URL |

```toml
[notifications.slack]
webhook_url_env = "SLACK_WEBHOOK_URL"
```

Sends a Block Kit message with title, due date, priority, and tags.

#### Webhook backend (generic HTTP POST)

Config keys in `[notifications.webhook]`:

| Key       | Description             | Default  |
|-----------|-------------------------|----------|
| `url`     | Full endpoint URL       | required |
| `method`  | HTTP method             | `POST`   |
| `headers` | Dict of request headers | `{}`     |

Header values support `$VAR` environment variable expansion.

```toml
[notifications.webhook]
url    = "https://hooks.example.com/notify"
method = "POST"
headers = { "Authorization" = "Bearer $NOTIFY_TOKEN" }
```

Returns `true` for 2xx responses, `false` for 3xx and above.

### Force-sending a notification

```bash
mdone notify --send abc12345
mdone notify --send abc12345 --backend slack
mdone notify --send abc12345 --backend webhook --json
```

### Re-arming notifications

```bash
mdone notify --reset-all      # re-enable all
mdone notify --reset abc12345 # re-enable one task
```

### Daemon mode (human use)

```bash
mdone notify --daemon
mdone notify --daemon --interval 30
```

The daemon polls every `poll_interval` seconds (default 60), sends via the configured backend, and records sent IDs in `.notified`. Stop with Ctrl-C.

---

## 12. Search Algorithm

`mdone search QUERY` uses a weighted full-text scoring model.

### Tokenization

The query is split on whitespace and commas, lowercased. Each token is independently matched.

### Scoring weights

| Field      | Weight | Notes                         |
|------------|--------|-------------------------------|
| `title`    | ×3     | Substring match per token     |
| `tags`     | ×2     | Match against each tag        |
| `contexts` | ×1     | Match against each context    |
| `due`      | ×1     | Match against ISO date string |
| `recur`    | ×1     | Match against recur rule      |

A match is counted when the token appears as a substring of the field value (case-insensitive). The score is the weighted sum of all matches. Tasks with score 0 are excluded.

### Sort order

Results are sorted by: descending score → ascending title (alphabetical).

### `matched_fields`

The JSON output includes `matched_fields`, a list of field names that contributed to the score.

---

## 13. Configuration File

Location: `$TODO_DIR/config.toml` (default `~/.todo/config.toml`)

Create with: `mdone config --init`

### Full schema with defaults

```toml
# ── General ──────────────────────────────────────────────────────────────────
[general]
# strftime format for human-readable date display
# Storage always uses ISO 8601 regardless of this setting
date_format      = "%Y-%m-%d"

# Default priority for new tasks that don't specify one (1=urgent … 4=none)
default_priority = 4

# ── Tags ─────────────────────────────────────────────────────────────────────
[tags]
# Tags automatically added to every new task via `add`
# default_tags = ["work", "q2"]
default_tags = []

# ── Notifications ─────────────────────────────────────────────────────────────
[notifications]
# Delivery backend: stdout | os | email | slack | webhook
backend = "stdout"

# Default notify lead time for tasks with a due: but no notify: field.
# Leave empty ("") to disable.
# e.g. "1h" fires 1 hour before due.
default_notify = ""

# Daemon poll interval in seconds
poll_interval = 60

# ── Email (SMTP) ─────────────────────────────────────────────────────────────
# [notifications.email]
# smtp_host    = "smtp.gmail.com"
# smtp_port    = 587
# from         = "todo-agent@example.com"
# to           = "you@example.com"
# username_env = "SMTP_USER"
# password_env = "SMTP_PASSWORD"

# ── Slack ─────────────────────────────────────────────────────────────────────
# [notifications.slack]
# webhook_url_env = "SLACK_WEBHOOK_URL"

# ── Generic webhook (Teams / Discord / Zapier / n8n) ─────────────────────────
# [notifications.webhook]
# url     = "https://hooks.example.com/notify"
# method  = "POST"
# headers = { "Authorization" = "Bearer $NOTIFY_TOKEN" }
```

### Config loading precedence

1. User `config.toml` (highest priority)
2. Built-in defaults (lowest priority)

User values are deep-merged into defaults. A partial config inherits all unset defaults. Read the effective merged config with `mdone config --show --json`.

---

## 14. Agent Integration Guide

This section describes recommended patterns for AI agents using ¯\(ツ)/¯mdone.

### Setup

```bash
# Install
pip install .

# (Optional) isolate to a project-specific directory
export TODO_DIR=/path/to/project/.todo

# (Optional) initialize config
mdone config --init
```

### General principles

- Always use `--json` for structured output; use `--json-pretty` only for debugging
- Every JSON response is `{"schema_version": 1, "data": <payload>}` — always read `response["data"]`
- Assert `schema_version == 1` at startup; any increment means a breaking data change
- Use `--dry-run` before any destructive or mutating operation to verify parsed intent
- Check exit codes: `0` = success, `1` = not found, `2` = bad input, `3` = no results
- IDs are stable — store them when referencing tasks across calls
- Every task JSON object includes `section` — use it to understand where a task sits

### Pattern: Add a task safely

```bash
# Step 1: dry-run to confirm parse and section assignment
mdone add "Fix authentication bug @work due:tomorrow priority:1 notify:2h" --dry-run
# → { "section": "today", ... }

# Step 2: add for real and capture the ID
mdone add "Fix authentication bug @work due:tomorrow priority:1 notify:2h" --json
# → { "id": "abc12345", "section": "today", ... }
```

Override section when auto-assignment doesn't match intent:

```bash
mdone add "Investigate option B" --section someday --json
mdone add "Waiting on design sign-off" --section waiting --json
```

### Pattern: List and process tasks

```bash
# All open tasks as JSON (includes section on each task)
mdone list --json

# Tasks in a specific section
mdone list --section today --json
mdone list --section inbox --json

# Priority-1 tasks due today
mdone list --priority 1 --due today --json

# All overdue tasks
mdone list --overdue --json

# Tasks by tag
mdone list --tag work --json
```

### Pattern: Update a task

```bash
# Preview the change
mdone edit abc12345 --set priority:1 --set due:tomorrow --dry-run

# Apply if dry-run looks correct
mdone edit abc12345 --set priority:1 --set due:tomorrow --json

# Move task to waiting
mdone edit abc12345 --set section:waiting --json
```

### Pattern: Organize after bulk edits

After assigning or changing due dates on multiple tasks, run `organize` to move them to the right sections and sort within each section:

```bash
# Preview
mdone organize --sort priority --dry-run

# Apply: reassign sections + sort by priority
mdone organize --sort priority --json
# → {"schema_version":1,"data":{"archived":[],"moved":[{"id":"...","from":"inbox","to":"upcoming",...}],"sorted_by":"priority"}}

# Just sort without changing sections
mdone organize --sort due --json
# → {"schema_version":1,"data":{"archived":[],"moved":[],"sorted_by":"due"}}
```

### Pattern: Complete a recurring task

```bash
# Preview: check if this task recurs and what gets spawned
mdone done abc12345 --dry-run

# Complete it; spawned task inherits the parent's section
mdone done abc12345 --json
# → {"schema_version":1,"data":[{"completed":{...},"spawned":{"id":"xyz99887","section":"today",...},"dry_run":false}]}

# Re-organize spawned task based on its new due date, sort by priority
mdone organize --sort priority --json
# → {"schema_version":1,"data":{"archived":[],"moved":[...],"sorted_by":"priority"}}
```

### Pattern: Notification dispatch (recommended)

This is the core agent notification loop. Run it periodically (cron, async loop, scheduled task):

```bash
# 1. Get pending notifications
PENDING=$(mdone notify --check --json)

# 2. For each item in PENDING: dispatch via your own channel
#    (email API, Slack SDK, push notification, etc.)
#    Payload fields: id, title, due, notify, priority, tags, overdue, minutes_until_due

# 3. Record as sent to prevent re-delivery
mdone notify --mark-sent abc12345 def67890
```

**Python example**:

```python
import json
import subprocess

result = subprocess.run(
    ["mdone", "notify", "--check", "--json"],
    capture_output=True, text=True
)
response = json.loads(result.stdout)
assert response["schema_version"] == 1  # guard against breaking changes
pending = response["data"]

ids_sent = []
for task in pending:
    # your_channel.send(task["title"], task["due"])  # dispatch here
    ids_sent.append(task["id"])

if ids_sent:
    subprocess.run(["mdone", "notify", "--mark-sent"] + ids_sent)
```

### Pattern: Daily recap

```bash
# Get today's overdue + due tasks
mdone recap --json

# Get full week view
mdone recap --week --json
```

### Pattern: Triage unscheduled tasks

```bash
# Find tasks needing triage
mdone triage --json

# For each task, assign due date or priority
mdone edit abc12345 --set due:next-friday --json
mdone edit def67890 --set priority:2 --json

# Auto-move newly scheduled tasks to the right section and sort by priority
mdone organize --sort priority --json
# → {"schema_version":1,"data":{"archived":[],"moved":[...],"sorted_by":"priority"}}
```

### Pattern: Section-based workflow management

```bash
# See the full picture
mdone list --json | jq '.data | group_by(.section)'

# Focus: what's on my plate right now?
mdone list --section today --json

# What's coming up?
mdone list --section upcoming --sort due --json

# What's parked?
mdone list --section someday --json

# What am I waiting on?
mdone list --section waiting --json

# Move a task you're now unblocked on
mdone edit abc12345 --set section:today --json
```

### Pattern: Snooze interruptions

```bash
# Snooze until tomorrow morning (hide from list/recap)
mdone snooze abc12345 1d --json

# Clear snooze to resurface immediately
mdone snooze abc12345 --clear --json
```

### Cron / scheduled task setup

```cron
# Check notifications every 5 minutes
*/5 * * * * /usr/local/bin/mdone notify --check --json | your-dispatch-script

# Auto-organize + sort by priority each morning
0 7 * * * /usr/local/bin/mdone organize --sort priority --json

# Daily morning recap
0 8 * * * /usr/local/bin/mdone recap --json | your-summary-script
```

### Complete task workflow (agent orchestration example)

```
1. USER: "remind me to submit Q2 report by Friday, it's urgent"

2. AGENT: mdone add -n "remind me to submit Q2 report by Friday, it's urgent" --dry-run
   → {"schema_version":1,"data":{"title":"Submit Q2 report","due":"2026-04-18","priority":1,"tags":["work"],"section":"upcoming",...}}

3. AGENT: (user confirms) mdone add -n "..." --json
   → {"schema_version":1,"data":{"id":"rp9km3xz","section":"upcoming",...}}

4. CRON: 0 7 * * * mdone organize --sort priority --json   (Friday arrives)
   → {"schema_version":1,"data":{"archived":[],"moved":[{"id":"rp9km3xz","from":"upcoming","to":"today","due":"2026-04-18"}],"sorted_by":"priority"}}

5. CRON: mdone notify --check --json  (runs every N minutes)
   → {"schema_version":1,"data":[{"id":"rp9km3xz","overdue":false,"minutes_until_due":480,...}]}

6. AGENT: dispatch email/Slack/etc. with response["data"][0]
   AGENT: mdone notify --mark-sent rp9km3xz

7. USER: "mark Q2 report done"

8. AGENT: mdone done rp9km3xz --json
   → {"schema_version":1,"data":[{"completed":{...},"spawned":null,"dry_run":false}]}
```

---

## 15. Human User Guide

### Quick start

```bash
# Install
pip install .

# Add your first task
mdone add "Buy groceries @shopping due:today"

# See what's on (grouped by section)
mdone list

# Mark done
mdone done <id>
```

### Daily workflow

```bash
# Morning check
mdone recap

# Auto-organize overnight changes and sort by priority
mdone organize --sort priority

# See the week ahead
mdone recap --week

# Focus on today's tasks
mdone list --section today

# Add tasks throughout the day
mdone add "Call dentist"                              # → Inbox
mdone add "Fix CSS bug @work due:tomorrow priority:2" # → Upcoming
mdone add "Parked idea" --section someday

# Mark tasks done
mdone done abc12345

# Set up tab-completion (one time)
mdone completions --install
```

### Using NLP mode

When you don't want to remember the syntax:

```bash
mdone add -n "remind me to call Alice next Friday at 3pm"
mdone add -n "urgent: fix the login bug by tomorrow"
mdone add -n "dentist appointment on May 5th"
mdone add -n "buy groceries this weekend"
```

NLP mode auto-assigns the section from the extracted due date, same as mini-syntax mode.

### Working with sections

```bash
# See everything, grouped by section
mdone list

# Focus on one section
mdone list --section today
mdone list --section inbox
mdone list --section someday

# Add directly to a section
mdone add "Waiting on legal review" --section waiting
mdone add "Someday: write a novel" --section someday

# Move a task
mdone edit abc12345 --set section:today

# Auto-reassign all tasks based on due dates
mdone organize

# Auto-reassign and sort within sections by priority
mdone organize --sort priority

# Auto-reassign and sort within sections by due date
mdone organize --sort due
```

### Managing due dates

```bash
# Relative dates
mdone add "Task due:tomorrow"
mdone add "Task due:next-friday"
mdone add "Task due:in-3-days"
mdone add "Task due:in-1-month"

# With specific time
mdone add "Meeting due:2026-04-15T14:00"

# Edit due date, then organize to move to the right section and sort
mdone edit abc12345 --set due:next-monday
mdone organize --sort priority
```

### Notifications (human setup)

```bash
# Initialize config
mdone config --init

# Edit ~/.todo/config.toml to set backend and credentials

# Test notification for a task
mdone notify --send abc12345

# Start daemon for automatic delivery
mdone notify --daemon
```

### Organizing with tags and priority

```bash
# Tag at add time
mdone add "Write tests @work priority:2"
mdone add "Grocery run @shopping"

# Filter by tag
mdone list --tag work
mdone list --tag shopping

# Filter by priority
mdone list --priority 1
mdone list --priority 2

# See only overdue
mdone list --overdue
```

### Snoozing tasks

```bash
# Hide for 2 hours (stays in its section, just hidden)
mdone snooze abc12345 2h

# Hide until next morning
mdone snooze abc12345 1d

# Hide until a specific time
mdone snooze abc12345 2026-04-20T09:00

# Reveal a snoozed task early
mdone snooze abc12345 --clear

# See all tasks including snoozed
mdone list --all
```

### Triage workflow

For tasks you've quickly captured without planning:

```bash
# Interactive: step through unscheduled tasks
mdone triage
# Options: [d]ue date, [p]riority, [t]ag, [s]kip, [q]uit

# After assigning due dates, move tasks to the right section and sort
mdone organize --sort priority
```

### Finding old tasks

```bash
# Search active tasks
mdone search "login"
mdone search "bug" --tag work

# Search completed tasks too
mdone search "old project" --archive
```

### Recurring tasks

```bash
# Daily standup
mdone add "Stand-up @work due:today recur:daily"

# Weekly review
mdone add "Weekly review @work due:next-friday recur:weekly priority:2"

# Monthly bills
mdone add "Pay rent @finance due:2026-05-01 recur:monthly priority:1"

# When you mark these done, the next occurrence is created in the same section
mdone done abc12345
# ↻ Next: xyz99887  Stand-up  due:2026-04-16

# Run organize to move it if the new due date has passed, sort by due date
mdone organize --sort due
```

### Configuration tips

```bash
# Create config
mdone config --init

# View current settings
mdone config --show
```

Useful config tweaks in `~/.todo/config.toml`:

```toml
[general]
# Show dates as "Apr 15" instead of "2026-04-15"
date_format = "%b %d"

[tags]
# Auto-tag everything with your current project
default_tags = ["work", "q2-2026"]

[notifications]
# Get notified 1 hour before everything that has a due date
default_notify = "1h"
backend = "os"
```

### Shell completions

```bash
# Auto-detect and install
mdone completions --install

# Or manually for your shell
mdone completions --shell bash >> ~/.bash_completion
mdone completions --shell zsh > ~/.zsh/completions/_mdone
mdone completions --shell fish > ~/.config/fish/completions/mdone.fish
```

After installing, restart your shell or source the file.
