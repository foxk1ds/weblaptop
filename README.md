# weblaptop

A terminal coding agent for your LAN. Weblaptop runs a ReAct loop against an
Ollama server, executes tools in your working directory, and keeps the
terminal readable while it does it.

- **BUILD** executes tools directly.
- **PLAN** reads freely and asks before any mutation.
- Every action is one aligned line; output sits behind a light gutter with its
  exit code and duration.
- A single design system (`weblaptop/theme.py`) governs the palette, glyphs,
  spacing, and formatting, so every screen belongs to the same product.

---

## Interface

```
  ♪  weblaptop  0.1.0                              ● online  4 ms
     qwen2.5-coder:latest · ~/weblaptop · git:master · medium · BUILD

▸ Bash   $ .venv/bin/python -m unittest discover tests
│ ........................................
│ Ran 36 tests in 0.028s
│ OK
╰ exit 0 · 52 ms

▸ Read    weblaptop/ui.py
✓ Read weblaptop/ui.py   ·   380 lines · 14.2 KB

▌ weblaptop   qwen2.5-coder:latest

The build passes. I updated the header and reran the suite.
```

The header folds on narrow terminals instead of wrapping. The prompt carries
the active mode as a solid pill:

```
 BUILD  ❯  describe the change
 PLAN   ❯  review the diff
```

`/status`, `/help`, `/history`, and `/config` answer in compact, aligned
tables. Approval is the only boxed surface: an amber card with the full
command or a clipped diff, followed by a single line of choices.

### Key bindings

| Key | Action |
| --- | --- |
| `tab` | toggle BUILD / PLAN on an empty prompt |
| `/` | commands and sub-options |
| `@` | fuzzy file referencing |
| `!` | run a shell command inline |
| `ctrl+r` | search command history |
| `ctrl+c` | interrupt the current turn |
| `ctrl+d` | exit |

---

## Install

```bash
cd /home/foxkids/weblaptop
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo ln -sf /home/foxkids/weblaptop/bin/weblaptop /usr/local/bin/weblaptop
```

Verify the launcher:

```bash
weblaptop --version
weblaptop --help
```

---

## Usage

### Interactive REPL

```bash
weblaptop
```

This measures the LAN round-trip, renders the header, and drops you into the
shell in BUILD mode.

### Read-only planning

```bash
weblaptop --plan
weblaptop --plan "review the diff and explain the risk"
```

PLAN mode reads files freely and shows an approval card before any mutation.
Toggle modes with `tab` on an empty prompt or `/mode`.

### Single-task execution

```bash
weblaptop "inspect the current directory"
weblaptop "review the diff and run cargo test"
```

### Autonomous execution

BUILD already runs tools without prompts. `--yolo` states that intent
explicitly, which is useful in scripts:

```bash
weblaptop --yolo "find and fix the memory leak in main.c"
```

### Custom model or endpoint

```bash
weblaptop --server http://192.168.100.106:11434 --model qwen2.5:7b

export WEBLAPTOP_SERVER="http://192.168.100.106:11434"
export WEBLAPTOP_MODEL="qwen2.5:7b"
```

### Model discovery

weblaptop asks the server which models it actually has; nothing is assumed.
If the configured model is not installed, the first model the server reports
is used and the switch is shown.

```bash
weblaptop --models
weblaptop --server http://192.168.100.106:11434 --models
```

`/model` in the REPL lists the same server-reported models and warns when a
name you set is not installed.

### Slash commands

| Command | Purpose |
| --- | --- |
| `/mode build\|plan` | switch agent mode |
| `/model [name]` | select a model or list server models |
| `/effort [level]` | `off`, `low`, `medium`, `high`, `max` |
| `/config [show\|set\|reset]` | inspect or edit runtime settings |
| `/status` | connection, model, effort, and limits |
| `/compact` | compact the conversation context |
| `/history` | view conversation turns and tool calls |
| `/system` | view the active system prompt |
| `/clear` | clear the screen and redraw the header |
| `/reset` | forget the conversation context |
| `/help` | command, input, and key reference |
| `/exit`, `/quit` | leave weblaptop |

`@path/to/file` attaches file contents to the next prompt. `!command` runs a
shell command inline, using the same action line and gutter as the agent.

---

## Project structure

```
weblaptop/
├── bin/weblaptop              executable launcher
├── weblaptop/
│   ├── cli.py                 argument parsing and dispatch
│   ├── config.py              runtime configuration and LAN defaults
│   ├── client.py              Ollama client (ping, models, streaming chat)
│   ├── agent.py               ReAct loop and response parsing
│   ├── repl.py                prompt_toolkit REPL, completion, slash commands
│   ├── banner.py              header and status views
│   ├── ui.py                  notices, action lines, gutters, Markdown
│   ├── safety.py              approval gate, diff preview, editor handoff
│   ├── theme.py               palette, glyphs, spacing, formatting helpers
│   └── tools/                 bash and filesystem tools
└── tests/
    ├── test_ui.py             layout, truncation, header, helpers
    ├── test_agent_mock.py     ReAct loop end-to-end
    ├── test_opencode.py       modes and configuration
    ├── test_slash_shortcuts.py completion and slash handlers
    └── test_weblaptop.py      core unit tests
```

---

## Tests

```bash
.venv/bin/python -m unittest discover tests
```
