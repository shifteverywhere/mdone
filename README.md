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

## Using with an AI agent

mdone is designed to work as the task layer behind an AI assistant. The agent listens to your natural conversation, extracts tasks, and manages them through the CLI — you never need to touch the syntax yourself.

A ready-to-use system prompt template is included in [`agent-prompt-template.md`](agent-prompt-template.md). Copy it into your agent's system prompt, fill in the placeholders (your name, timezone, notification channel, etc.), and the agent will:

- Capture tasks from how you naturally talk
- Confirm before saving, using plain English
- Surface overdue tasks at the start of each session
- Handle notifications and route them to your preferred channel
- Run weekly reviews and triage on request

### Natural language examples

You don't need to know any mdone syntax. Just talk, and the agent picks it up:

| You say | Agent creates |
|---|---|
| *"Remind me to send the invoice to Acme by end of Friday"* | Task in **Upcoming**, due Friday, @work |
| *"I need to book a dentist appointment, not urgent but soon"* | Task in **Inbox**, @health |
| *"Can you track that I'm waiting on Sarah for the contract?"* | Task in **Waiting** |
| *"Urgent: the staging server is down, needs fixing today"* | Task in **Today**, priority 1 |
| *"Someday I'd like to learn Rust"* | Task in **Someday** |
| *"Stand-up every morning at 9, remind me 10 minutes before"* | Recurring daily task, notify:10m |
| *"What's on my plate today?"* | Agent runs `mdone list --section today` and summarises |
| *"Mark the invoice task as done"* | Agent finds it via search and runs `mdone done` |

### Setting up the agent

1. Open [`agent-prompt-template.md`](agent-prompt-template.md)
2. Copy the prompt block (everything inside the code fences)
3. Fill in your preferences — name, timezone, notification channel, etc.
4. Paste it as the system prompt of your AI assistant

The template includes a placeholder reference table at the bottom.

## Full reference

See [DOCUMENTATION.md](DOCUMENTATION.md) for the complete command reference, JSON schemas, agent integration patterns, and configuration options.

## License

MIT
