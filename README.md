# ¯\(ツ)/¯mdone

A Markdown-native, AI-agent-friendly CLI todo manager. Tasks live in a plain `tasks.md` file — human-readable, hand-editable, and structured enough for agents to reliably parse and mutate.

## Install

**Via pip (directly from GitHub):**

```bash
pip install git+https://github.com/shifteverywhere/mdone.git
```

**From source:**

```bash
git clone https://github.com/shifteverywhere/mdone.git
cd mdone
pip install .
```

## Quick start

```bash
# Add tasks
mdone add "Buy groceries @shopping due:today"
mdone add "Fix login bug @work due:tomorrow priority:1"
mdone add "Parked idea" --section someday

# See what's on
mdone list

# Mark done
mdone done <id>

# Auto-organise by due date, sort by priority
mdone organize --sort priority
```

## Features

- **Five sections** — Inbox, Today, Upcoming, Someday, Waiting — auto-assigned from due dates
- **Mini-syntax** — inline `due:`, `priority:`, `@tag`, `recur:`, `notify:` fields
- **NLP mode** — `mdone add -n "remind me to call Alice next Friday"`
- **Recurrence** — daily / weekly / monthly, spawns next occurrence on completion
- **Notifications** — pull model via `mdone notify --check --json`; backends: stdout, OS, email, Slack, webhook
- **Agent-safe** — every command supports `--dry-run` and `--json`; stable exit codes

## Full reference

See [DOCUMENTATION.md](DOCUMENTATION.md) for the complete command reference, JSON schemas, agent integration patterns, and configuration options.

## License

MIT
