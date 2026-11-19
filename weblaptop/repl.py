"""
Interactive REPL for weblaptop.

The shell is deliberately quiet: a mode pill, a single arrow, and one
toolbar line carrying state. Commands answer in short aligned blocks, and
the agent's work appears as one action line per tool followed by its
output.
"""

import os
import re
import sys
import time
from typing import Callable, List, Optional, Tuple

from prompt_toolkit import PromptSession
from prompt_toolkit.application import get_app
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from rich.padding import Padding
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from weblaptop.agent import Agent, build_system_prompt
from weblaptop.banner import render_status_line, render_status_panel
from weblaptop.client import OllamaClient
from weblaptop.config import Config, VALID_EFFORTS
from weblaptop.theme import CARD, GLYPHS, display_path, mid_truncate, plural, style
from weblaptop.tools.bash import run_bash
from weblaptop.tools.filesystem import read_file
from weblaptop.ui import (
    console,
    print_notice,
    print_blank,
    print_section,
    print_tool_call,
    print_tool_result,
)


OPENCODE_COMMANDS = [
    ("/mode", "Switch agent mode: BUILD (autonomous) or PLAN (safe)"),
    ("/model", "Select or switch active LLM model"),
    ("/effort", "Set reasoning effort: off, low, medium, high, max"),
    ("/reasoning", "Alias for /effort"),
    ("/yolo", "Toggle BUILD (autonomous) vs PLAN (safe) mode"),
    ("/status", "Show connection ping, active model, and stats"),
    ("/compact", "Compact conversation context history"),
    ("/config", "Inspect or edit configuration parameters"),
    ("/history", "View conversation history turns"),
    ("/system", "Inspect active system prompt & guidelines"),
    ("/clear", "Clear terminal screen and redraw header"),
    ("/reset", "Reset conversation context"),
    ("/help", "List available commands and shortcuts"),
    ("/exit", "Exit weblaptop REPL"),
    ("/quit", "Alias for /exit"),
]

EFFORT_OPTIONS = [
    ("off", "Minimal thinking (temp: 0.1)"),
    ("low", "Concise reasoning (~1k tokens, temp: 0.2)"),
    ("medium", "Balanced reasoning (default, temp: 0.3)"),
    ("high", "Deep reasoning (~16k tokens, temp: 0.5)"),
    ("max", "Exhaustive analytical depth (temp: 0.7)"),
]

CONFIG_KEYS = [
    ("mode", "Agent mode (build/plan)"),
    ("effort", "Reasoning effort (off/low/medium/high/max)"),
    ("model", "Default model name"),
    ("temperature", "LLM sampling temperature (0.0 - 2.0)"),
    ("server", "Ollama server URL"),
    ("max_steps", "Maximum autonomous ReAct steps"),
    ("timeout", "Network request timeout in seconds"),
    ("cwd", "Working directory path"),
]


# ---------------------------------------------------------------------------
# Theme for prompt_toolkit (shares the palette from weblaptop.theme)
# ---------------------------------------------------------------------------

opencode_style = Style.from_dict({
    # Mode pill: solid background, dark text.
    "prompt-build": "bg:#a6e3a1 #11111b bold",
    "prompt-plan": "bg:#f9e2af #11111b bold",
    "prompt-arrow": "#89b4fa bold",
    "prompt-text": "#cdd6f4",
    "input": "#cdd6f4",
    "placeholder": "#6c7086 italic",
    # Floating completion menu.
    "completion-menu": "bg:#181825 #cdd6f4",
    "completion-menu.completion": "bg:#1e1e2e #cdd6f4",
    "completion-menu.completion.current": "bg:#313244 #89b4fa bold",
    "completion-menu.meta": "bg:#181825 #6c7086 italic",
    "completion-menu.meta.current": "bg:#313244 #cdd6f4",
    # Bottom toolbar.
    "toolbar": "bg:#181825 #6c7086",
    "toolbar-key": "bg:#181825 #a6adc8",
    "toolbar-model": "bg:#181825 #89b4fa",
    "toolbar-pad": "bg:#181825 #181825",
    "scrollbar.background": "bg:#11111b",
    "scrollbar.button": "bg:#45475a",
})


def _section(label: str, meta: str = "") -> None:
    print_section(label, meta)


def _config_grid(config: Config) -> Table:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=style("muted"), no_wrap=True)
    grid.add_column(style=style("text"))
    grid.add_row("model", config.model)
    grid.add_row("mode", f"{config.mode.upper()}")
    grid.add_row("effort", f"{config.reasoning_effort}  (temperature {config.effective_temperature:.2f})")
    grid.add_row("server", config.server_url)
    grid.add_row("directory", config.cwd)
    grid.add_row("max steps", str(config.max_steps))
    grid.add_row("timeout", f"{config.timeout:.0f}s")
    return grid


def handle_config_command(config: Config, agent: Agent, command_arg: str) -> None:
    """Handle /config [show | set <key> <val> | reset]."""
    arg = command_arg.strip()

    if arg.startswith("set "):
        sub_parts = arg.split(maxsplit=2)
        if len(sub_parts) == 3:
            _, key, value = sub_parts
            ok, message = config.set_value(key, value)
            agent.update_system_prompt()
            print_notice(message, "ok" if ok else "error")
        else:
            print_notice("usage: /config set <key> <value>", "warn")
        return

    if arg == "reset":
        fresh = Config()
        config.model = fresh.model
        config.reasoning_effort = fresh.reasoning_effort
        config.mode = fresh.mode
        config.yolo = fresh.yolo
        agent.update_system_prompt()
        print_notice("configuration reset to defaults", "ok")
        return

    _section("configuration")
    console.print(Padding(_config_grid(config), (0, 0, 0, 4), expand=False))
    console.print()


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

class OpenCodeCompleter(Completer):
    """
    OpenCode-style auto-completer supporting:
    - '/' for slash commands
    - '@' for project file fuzzy referencing
    """

    CACHE_TTL = 2.0
    MAX_FILES = 4000

    def __init__(
        self,
        cwd_cb: Optional[Callable[[], str]] = None,
        get_models_cb: Optional[Callable[[], List[str]]] = None,
    ):
        self.cwd_cb = cwd_cb or (lambda: ".")
        self.get_models_cb = get_models_cb or (lambda: [])
        self._file_cache: List[str] = []
        self._cache_cwd: Optional[str] = None
        self._cache_at = 0.0

    def _project_files(self, cwd: str) -> List[str]:
        """Cache the project file list briefly so typing stays responsive."""
        now = time.monotonic()
        if self._cache_cwd == cwd and (now - self._cache_at) < self.CACHE_TTL:
            return self._file_cache

        files: List[str] = []
        for root, dirs, names in os.walk(cwd):
            dirs[:] = [
                d for d in dirs
                if not d.startswith(".")
                and d not in ("node_modules", "target", "build", "dist", "__pycache__", ".venv")
            ]
            for name in names:
                files.append(os.path.relpath(os.path.join(root, name), cwd))
                if len(files) >= self.MAX_FILES:
                    break
            if len(files) >= self.MAX_FILES:
                break

        self._file_cache = files
        self._cache_cwd = cwd
        self._cache_at = now
        return files

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor

        # 1. OpenCode '@' file referencing
        at_idx = text.rfind("@")
        if at_idx != -1:
            segment = text[at_idx:]
            if not any(ch in segment for ch in (" ", "\t", "\n")):
                query = segment[1:].lower()
                cwd = self.cwd_cb()
                matches = [
                    rel for rel in self._project_files(cwd)
                    if not query or query in rel.lower()
                ]
                for rel in sorted(matches)[:15]:
                    yield Completion(
                        f"@{rel}",
                        start_position=-(len(query) + 1),
                        display=f"@{rel}",
                        display_meta="file context",
                    )
                return

        # 2. OpenCode '/' slash commands
        if text.startswith("/"):
            parts = text.split()
            first = parts[0].lower() if parts else ""
            has_trailing_space = text.endswith(" ")

            if first in ("/effort", "/reasoning"):
                prefix = "" if (len(parts) == 1 and has_trailing_space) else (parts[1].lower() if len(parts) == 2 else None)
                if prefix is not None:
                    for level, desc in EFFORT_OPTIONS:
                        if level.startswith(prefix):
                            yield Completion(level, start_position=-len(prefix), display=level, display_meta=desc)
                    return

            if first == "/mode":
                prefix = "" if (len(parts) == 1 and has_trailing_space) else (parts[1].lower() if len(parts) == 2 else None)
                if prefix is not None:
                    yield Completion("build", start_position=-len(prefix), display="build", display_meta="autonomous execution")
                    yield Completion("plan", start_position=-len(prefix), display="plan", display_meta="read-only planning")
                    return

            if first == "/model":
                prefix = "" if (len(parts) == 1 and has_trailing_space) else (parts[1].lower() if len(parts) == 2 else None)
                if prefix is not None:
                    for model in self.get_models_cb():
                        if model.lower().startswith(prefix):
                            yield Completion(model, start_position=-len(prefix), display=model, display_meta="ollama model")
                    return

            if first == "/config":
                if (len(parts) == 1 and has_trailing_space) or (len(parts) == 2 and not has_trailing_space):
                    prefix = parts[1].lower() if len(parts) == 2 else ""
                    for sub, desc in [("show", "show configuration"), ("set", "set config value"), ("reset", "reset to defaults")]:
                        if sub.startswith(prefix):
                            yield Completion(sub, start_position=-len(prefix), display=sub, display_meta=desc)
                    return
                elif len(parts) >= 2 and parts[1] == "set":
                    prefix = parts[2].lower() if len(parts) == 3 else ""
                    for key, desc in CONFIG_KEYS:
                        if key.startswith(prefix):
                            yield Completion(key, start_position=-len(prefix), display=key, display_meta=desc)
                    return

            # Top-level slash commands
            query = text.lower()
            for cmd, desc in OPENCODE_COMMANDS:
                if cmd.startswith(query):
                    yield Completion(cmd, start_position=-len(text), display=cmd, display_meta=desc)


# Alias for backwards compatibility
AntigravitySlashCompleter = OpenCodeCompleter


# ---------------------------------------------------------------------------
# Command output
# ---------------------------------------------------------------------------

def _help_block(title: str, rows: List[Tuple[str, str]]) -> None:
    console.print(
        Text.assemble(
            ("    ", ""),
            (title.upper(), f"bold {style('muted')}"),
        )
    )
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=style("accent"), no_wrap=True, min_width=20)
    grid.add_column(style=style("subtle"))
    for key, description in rows:
        grid.add_row(key, description)
    console.print(Padding(grid, (0, 0, 1, 6), expand=False))


def show_help() -> None:
    """Display the command, input, and key reference."""
    _section("help")
    _help_block("commands", [
        ("/mode build|plan", "switch agent mode"),
        ("/model [name]", "select a model or list server models"),
        ("/effort [level]", "reasoning effort: off, low, medium, high, max"),
        ("/config [show|set]", "inspect or edit runtime settings"),
        ("/status", "connection, model, effort, and limits"),
        ("/compact", "compact the conversation context"),
        ("/history", "view conversation turns and tool calls"),
        ("/system", "view the active system prompt"),
        ("/clear", "clear the screen and redraw the header"),
        ("/reset", "forget the conversation context"),
        ("/exit, /quit", "leave weblaptop"),
    ])
    _help_block("input", [
        ("@file", "attach file contents to the prompt"),
        ("!command", "run a shell command inline"),
        ("/command", "run a slash command"),
    ])
    _help_block("keys", [
        ("tab", "toggle BUILD / PLAN on an empty prompt"),
        ("ctrl+r", "search command history"),
        ("ctrl+c", "interrupt the current turn"),
        ("ctrl+d", "exit"),
    ])
    console.print()


def _history_role(message: dict) -> Tuple[str, str]:
    content = str(message.get("content", "")).lstrip()
    role = message.get("role", "unknown")
    if content.startswith("Observation:"):
        return "observation", "warning"
    if role == "assistant":
        return "assistant", "accent"
    return role, "subtle"


def show_history(agent: Agent) -> None:
    """Display conversation history turns."""
    turns = [m for m in agent.history if m.get("role") != "system"]
    if not turns:
        print_notice("conversation history is empty", "info")
        return

    _section("history", plural(len(turns), "turn"))
    table = Table(
        box=None,
        show_header=True,
        header_style=style("muted"),
        pad_edge=False,
        padding=(0, 2),
        expand=False,
    )
    table.add_column("#", style=style("muted"), width=3, justify="right")
    table.add_column("role", width=12)
    table.add_column("content", no_wrap=True, overflow="ellipsis")

    for index, message in enumerate(turns, start=1):
        label, color = _history_role(message)
        content = str(message.get("content", "")).strip().replace("\n", " ")
        table.add_row(
            str(index),
            Text(label, style=f"bold {style(color)}"),
            Text(content, style=style("text") if label != "observation" else style("muted")),
        )

    console.print(Padding(table, (0, 0, 1, 2), expand=False))
    console.print()


def compact_history(agent: Agent) -> None:
    """Compact history by keeping the system prompt and recent turns."""
    turns = [m for m in agent.history if m.get("role") != "system"]
    if len(turns) <= 4:
        print_notice("history is already compact", "info")
        return

    recent = turns[-4:]
    agent.history = [agent.history[0]] + recent
    print_notice(
        "history compacted",
        "ok",
        detail=f"kept the last {len(recent)} turns",
    )


def _model_list(config: Config, models: List[str]) -> None:
    _section("models", f"{len(models)} available")
    grid = Table.grid(padding=(0, 2))
    grid.add_column(width=2, no_wrap=True)
    grid.add_column(style=style("text"), no_wrap=True)
    grid.add_column(style=style("muted"))
    for model in models:
        active = model == config.model
        grid.add_row(
            Text(GLYPHS["online"] if active else GLYPHS["bullet"], style=style("success") if active else style("border")),
            Text(model, style=f"bold {style('text')}" if active else style("text")),
            Text("active" if active else "", style=style("success")),
        )
    console.print(Padding(grid, (0, 0, 1, 4), expand=False))
    print_notice("switch with /model <name>", "info")


def handle_slash_command(
    command_line: str,
    config: Config,
    client: OllamaClient,
    agent: Agent,
) -> bool:
    """Handle a slash command; return True when the input was a command."""
    parts = command_line.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd in ("/exit", "/quit"):
        console.print(Text("  bye.", style=style("muted")))
        sys.exit(0)

    elif cmd == "/clear":
        console.clear()
        is_online, ping_ms, error = client.ping()
        render_status_line(console, config, ping_ms=ping_ms, is_online=is_online, error_msg=error)
        return True

    elif cmd == "/mode":
        if arg.lower() in ("build", "autonomous", "yolo"):
            config.mode = "build"
            config.yolo = True
        elif arg.lower() in ("plan", "safe"):
            config.mode = "plan"
            config.yolo = False
        else:
            config.toggle_mode()

        if config.is_autonomous:
            print_notice("mode set to BUILD", "ok", detail="autonomous execution")
        else:
            print_notice("mode set to PLAN", "ok", detail="read-only planning, mutations need approval")
        return True

    elif cmd in ("/effort", "/reasoning"):
        if arg.lower() in VALID_EFFORTS:
            config.reasoning_effort = arg.lower()
            agent.update_system_prompt()
            print_notice(
                f"effort set to {config.reasoning_effort}",
                "ok",
                detail=f"temperature {config.effective_temperature:.2f}",
            )
        else:
            print_notice(
                f"choose one of: {', '.join(VALID_EFFORTS)}",
                "warn",
                detail=f"current: {config.reasoning_effort}",
            )
        return True

    elif cmd == "/model":
        models, models_error = client.fetch_models()
        if arg:
            config.model = arg
            print_notice(f"model set to {config.model}", "ok")
            if models and arg not in models:
                print_notice(
                    f"{arg} is not installed on {config.server_url}",
                    "warn",
                    detail=f"available: {', '.join(models)}",
                )
        elif models:
            _model_list(config, models)
        elif models_error:
            print_notice("could not fetch models", "error", detail=models_error)
        else:
            print_notice(
                f"{config.server_url} reports no models",
                "warn",
                detail="pull one on that device, then retry /model",
            )
        return True

    elif cmd == "/compact":
        compact_history(agent)
        return True

    elif cmd == "/history":
        show_history(agent)
        return True

    elif cmd == "/yolo":
        config.yolo = not config.yolo
        config.mode = "build" if config.yolo else "plan"
        print_notice(
            f"mode set to {config.mode.upper()}",
            "ok",
            detail="autonomous execution" if config.is_autonomous else "read-only planning",
        )
        return True

    elif cmd == "/config":
        handle_config_command(config, agent, arg)
        return True

    elif cmd == "/status":
        is_online, ping_ms, error = client.ping()
        render_status_panel(console, config, ping_ms=ping_ms, is_online=is_online, error_msg=error)
        return True

    elif cmd == "/system":
        prompt = build_system_prompt(config)
        console.print(
            Panel(
                Syntax(prompt, "markdown", theme="github-dark", line_numbers=False),
                title="[bold]system prompt[/bold]",
                title_align="left",
                subtitle="[dim]reasoning guidelines follow the active effort[/dim]",
                subtitle_align="right",
                box=CARD,
                border_style=style("border"),
                padding=(0, 1),
            )
        )
        console.print()
        return True

    elif cmd == "/reset":
        agent.reset()
        print_notice("conversation reset", "ok", detail="system prompt retained")
        return True

    elif cmd == "/help":
        show_help()
        return True

    return False


def resolve_file_references(prompt: str, cwd: str) -> str:
    """
    OpenCode '@' file resolver: finds '@path/to/file' in prompt, reads the file,
    and prepends the file content as context.
    """
    at_tokens = re.findall(r"@([a-zA-Z0-9_\-\./\\]+)", prompt)
    if not at_tokens:
        return prompt

    attachments = []
    for token in at_tokens:
        full_path = os.path.join(cwd, token) if not os.path.isabs(token) else token
        if os.path.isfile(full_path):
            res = read_file(full_path, cwd=cwd)
            if res.get("success"):
                attachments.append(f"Content of @{token}:\n```\n{res.get('content')}\n```")
                print_notice(
                    f"attached @{token}",
                    "info",
                    detail=plural(int(res.get("total_lines", 0)), "line"),
                )

    if attachments:
        context_block = "\n\n".join(attachments)
        return f"{context_block}\n\nUser Request: {prompt}"
    return prompt


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def _toolbar(config: Config):
    """One state line under the prompt: keys on the left, state on the right."""
    left = (
        "  tab mode   " + GLYPHS["sep"] + "   / commands   "
        + GLYPHS["sep"] + "   @ files   " + GLYPHS["sep"] + "   ! shell"
    )
    model = mid_truncate(config.model, 24)
    cwd = mid_truncate(display_path(config.cwd), 28)
    right = f"{model}   {GLYPHS['sep']}   {cwd}  "

    try:
        width = get_app().output.get_size().columns
    except Exception:
        width = 80

    if width < 78:
        right = ""
    if width < 56:
        left = "  tab mode   " + GLYPHS["sep"] + "   / commands"
    pad = max(1, width - len(left) - len(right))
    return [
        ("class:toolbar", left),
        ("class:toolbar-pad", " " * pad),
        ("class:toolbar-model", right),
    ]


def run_repl(config: Config, client: OllamaClient, initial_prompt: Optional[str] = None) -> None:
    """Run the interactive REPL."""
    agent = Agent(config=config, client=client)

    # Initial probe & header, with feedback while the LAN round-trip runs.
    cached_models: List[str] = []
    models_error: Optional[str] = None
    with console.status(f"  [{style('muted')}]connecting…[/{style('muted')}]", spinner="dots") as status:
        is_online, ping_ms, error = client.ping()
        if is_online:
            status.update(f"  [{style('muted')}]loading models…[/{style('muted')}]")
            cached_models, models_error = client.fetch_models()

    render_status_line(
        console,
        config,
        ping_ms=ping_ms,
        is_online=is_online,
        error_msg=error,
    )

    # Report the server's real model list; never invent a model name.
    if is_online and not cached_models:
        if models_error:
            print_notice("could not read the model list", "warn", detail=models_error)
        else:
            print_notice(
                f"{config.server_url} reports no models",
                "warn",
                detail="pull one on that device, then run /model",
            )
    elif is_online and config.model not in cached_models:
        requested = config.model
        config.model = cached_models[0]
        print_notice(
            f"{requested} is not installed; using {config.model}",
            "info",
            detail=f"server reports: {', '.join(cached_models)}; switch with /model",
        )

    # If an initial prompt was passed on the CLI
    if initial_prompt:
        agent.run_task(initial_prompt)
        print_blank()

    # Dynamic model getter for autocomplete
    def get_models() -> List[str]:
        nonlocal cached_models
        if not cached_models and is_online:
            cached_models = client.get_models()
        return cached_models

    history_file = os.path.expanduser("~/.weblaptop_history")
    completer = OpenCodeCompleter(cwd_cb=lambda: config.cwd, get_models_cb=get_models)

    # Tab toggles [BUILD] vs [PLAN] on an empty prompt.
    kb = KeyBindings()

    @kb.add("tab")
    def _(event):
        buffer = event.current_buffer
        if not buffer.text.strip():
            config.toggle_mode()
            event.app.invalidate()
        else:
            buffer.complete_next()

    session = PromptSession(
        history=FileHistory(history_file),
        completer=completer,
        complete_while_typing=True,
        key_bindings=kb,
        style=opencode_style,
        placeholder="Ask anything, or type / for commands",
        bottom_toolbar=lambda: _toolbar(config),
    )

    while True:
        try:
            mode_tag = config.mode.upper()
            mode_style = "class:prompt-build" if config.is_autonomous else "class:prompt-plan"

            prompt_tokens = [
                (mode_style, f" {mode_tag} "),
                ("class:prompt-arrow", " ❯ "),
            ]

            user_input = session.prompt(prompt_tokens).strip()

            if not user_input:
                continue

            # 1. Inline shell execution ('!command')
            if user_input.startswith("!"):
                shell_cmd = user_input[1:].strip()
                if shell_cmd:
                    print_blank()
                    print_tool_call("run_bash", {"command": shell_cmd})
                    started = time.perf_counter()
                    result = run_bash(shell_cmd, cwd=config.cwd)
                    elapsed_ms = (time.perf_counter() - started) * 1000.0
                    print_tool_result("run_bash", result, duration_ms=elapsed_ms, cwd=config.cwd)
                continue

            # 2. Slash commands ('/cmd')
            if user_input.startswith("/"):
                handled = handle_slash_command(user_input, config, client, agent)
                if not handled:
                    print_notice(
                        f"unknown command: {user_input}",
                        "error",
                        detail="type /help for the command list",
                    )
                continue

            # 3. Resolve '@' file references
            enriched_prompt = resolve_file_references(user_input, config.cwd)

            # 4. Run the autonomous task loop
            print_blank()
            agent.run_task(enriched_prompt)
            print_blank()

        except KeyboardInterrupt:
            console.print()
            print_notice("interrupted", "warn", detail="ctrl+d or /exit to quit")
            continue
        except EOFError:
            console.print(Text("  bye.", style=style("muted")))
            break
        except Exception as exc:
            print_notice(f"error: {exc}", "error")
            console.print()
