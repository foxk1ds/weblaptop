"""
Terminal rendering primitives for weblaptop.

The interface follows one rule: quiet, aligned, and scannable. Status is
carried by a single accent bar, tool activity by one action line plus a
light gutter, and final answers by rendered Markdown under a `weblaptop`
heading. Only the approval gate is boxed.
"""

import textwrap
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

from weblaptop.theme import (
    GLYPHS,
    PALETTE,
    bold,
    format_bytes,
    format_duration,
    mid_truncate,
    plural,
    short_path,
    split_log,
    style,
)


console = Console(highlight=False)

MAX_OUTPUT_LINES = 18

_TOOL_LABELS = {
    "run_bash": "Bash",
    "write_file": "Write",
    "read_file": "Read",
    "search_dir": "Search",
}

_LABEL_WIDTH = max(len(label) for label in _TOOL_LABELS.values())


# ---------------------------------------------------------------------------
# Small shared pieces
# ---------------------------------------------------------------------------

def _notice_glyph(kind: str) -> tuple:
    return {
        "ok": (GLYPHS["check"], "success"),
        "error": (GLYPHS["cross"], "danger"),
        "warn": (GLYPHS["warn"], "warning"),
        "info": (GLYPHS["bullet"], "accent"),
    }.get(kind, (GLYPHS["bullet"], "accent"))


def print_notice(message: str, kind: str = "info", detail: str = "") -> None:
    """A single aligned status line: `  ✓ message  ·  detail`."""
    glyph, color = _notice_glyph(kind)
    line = Text.assemble(
        ("  ", ""),
        (glyph + " ", f"bold {style(color)}"),
        (message, style("text")),
    )
    if detail:
        line.append("   " + GLYPHS["sep"] + "   ", style=style("border"))
        line.append(detail, style=style("muted"))
    console.print(line)


def print_blank(count: int = 1) -> None:
    for _ in range(count):
        console.print()


def print_assistant_header(meta: str = "") -> None:
    """The `▌ weblaptop` heading that opens a final answer."""
    head = Text.assemble(
        ("  ", ""),
        (GLYPHS["bar"] + " ", f"bold {style('brand')}"),
        ("weblaptop", f"bold {style('text')}"),
    )
    if meta:
        head.append("   " + meta, style=style("muted"))
    console.print(head)


def print_section(label: str, meta: str = "") -> None:
    """A small heading for command output (models, history, config)."""
    console.print()
    line = Text.assemble(
        ("  ", ""),
        (label, f"bold {style('brand')}"),
    )
    if meta:
        line.append("   " + meta, style=style("muted"))
    console.print(line)


# ---------------------------------------------------------------------------
# Agent turn output
# ---------------------------------------------------------------------------

def print_step_header(step: int, max_steps: int) -> None:
    """Subtle step marker; the first step needs no introduction."""
    if step <= 1:
        return
    console.print()
    console.print(
        Text.assemble(
            ("  step ", style("muted")),
            (str(step), style("subtle")),
            (f"/{max_steps}", style("muted")),
        )
    )


def print_thought(thought: str) -> None:
    """Reasoning, rendered quietly so actions stand out."""
    body = thought.strip()
    if not body:
        return

    lines = body.splitlines()
    first = lines[0]
    console.print(
        Text.assemble(
            ("  " + GLYPHS["thought"] + " ", style("accent_dim")),
            (first, f"italic {style('muted')}"),
        )
    )
    for line in lines[1:]:
        if line.strip():
            console.print(
                Text.assemble(
                    ("  " + GLYPHS["thought"] + " ", style("accent_dim")),
                    (line.strip(), f"italic {style('muted')}"),
                )
            )


def _tool_detail(tool_name: str, args: Dict[str, Any]) -> tuple:
    """Return (detail Text, meta string) for an action line."""
    detail = Text()
    meta = ""

    if tool_name == "run_bash":
        detail.append("$ ", style=style("muted"))
        detail.append(str(args.get("command", "")), style=bold("accent"))
        cwd = args.get("cwd")
        if cwd:
            meta = short_path(str(cwd))
    elif tool_name in ("write_file", "read_file"):
        detail.append(str(args.get("path", "")), style=style("text"))
    elif tool_name == "search_dir":
        pattern = args.get("pattern") or "*"
        path = args.get("path") or "."
        detail.append(str(pattern), style=style("text"))
        detail.append("  in  ", style=style("muted"))
        detail.append(str(path), style=style("text"))
    else:
        detail.append(str(args or ""), style=style("muted"))

    return detail, meta


def print_tool_call(tool_name: str, args: Dict[str, Any]) -> None:
    """One line, printed before execution so the user always sees intent."""
    if tool_name == "finish":
        return

    label = _TOOL_LABELS.get(tool_name, tool_name.replace("_", " ").title())
    detail, meta = _tool_detail(tool_name, args)

    # Keep the action on one line: prefer keeping the command and dropping
    # the working directory, then truncate the command if it still overflows.
    prefix_width = 2 + 2 + _LABEL_WIDTH + 1
    available = max(12, console.width - prefix_width)
    meta_suffix = "   " + GLYPHS["sep"] + "   " + meta if meta else ""
    if len(detail.plain) + len(meta_suffix) > available:
        meta_suffix = ""
    detail_budget = max(8, available - len(meta_suffix))
    if len(detail.plain) > detail_budget:
        detail = Text(
            mid_truncate(detail.plain, detail_budget),
            style=bold("accent") if tool_name == "run_bash" else style("text"),
        )

    line = Text.assemble(
        ("  " + GLYPHS["action"] + " ", f"bold {style('accent')}"),
        (f"{label:<{_LABEL_WIDTH}}", f"bold {style('text')}"),
        (" ", ""),
    )
    line.append_text(detail)
    if meta_suffix:
        line.append(meta_suffix, style=style("muted"))
    console.print(line)


def _emit_log(lines: List[str], gutter_style: str, text_style: str) -> None:
    """Print plain log lines behind a light gutter, wrapping safely."""
    available = max(20, console.width - 5)
    clipped = split_log(lines, MAX_OUTPUT_LINES)
    omitted = len(lines) - MAX_OUTPUT_LINES if len(lines) > MAX_OUTPUT_LINES else 0

    for line in clipped:
        if line is None:
            console.print(
                Text.assemble(
                    ("  " + GLYPHS["gutter"] + " ", style("border")),
                    (f"… {omitted} lines omitted …", style("muted")),
                )
            )
            continue

        expanded = line.expandtabs(4)
        chunks = textwrap.wrap(
            expanded,
            width=available,
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
        for chunk in chunks:
            console.print(
                Text.assemble(
                    ("  " + GLYPHS["gutter"] + " ", gutter_style),
                    (chunk.rstrip(), text_style),
                )
            )


def _footer(parts: List[tuple]) -> None:
    line = Text.assemble(("  " + GLYPHS["corner"] + "─ ", style("border")))
    for index, (value, color) in enumerate(parts):
        if index:
            line.append(" " + GLYPHS["sep"] + " ", style=style("border"))
        line.append(value, style=style(color) if color in PALETTE else color)
    console.print(line)


def print_tool_result(
    tool_name: str,
    result: Dict[str, Any],
    duration_ms: Optional[float] = None,
    cwd: Optional[str] = None,
) -> None:
    """Render a tool result: output behind a gutter, outcome on the footer."""
    if tool_name == "run_bash":
        _print_bash_result(result, duration_ms)

    elif tool_name == "write_file":
        if result.get("success"):
            action = str(result.get("status", "saved")).capitalize()
            print_notice(
                f"{action} {short_path(str(result.get('path', '')), cwd or '')}",
                "ok",
                detail=(
                    f"{plural(int(result.get('lines_written', 0)), 'line')}"
                    f" {GLYPHS['sep']} {format_bytes(int(result.get('bytes_written', 0)))}"
                ),
            )
        else:
            print_notice(str(result.get("error", "write failed")), "error")

    elif tool_name == "read_file":
        if result.get("success"):
            detail = (
                f"{plural(int(result.get('total_lines', 0)), 'line')}"
                f" {GLYPHS['sep']} {format_bytes(int(result.get('size_bytes', 0)))}"
            )
            if result.get("truncated"):
                detail += " · truncated"
            print_notice(
                f"Read {short_path(str(result.get('path', '')), cwd or '')}",
                "ok",
                detail=detail,
            )
        else:
            print_notice(str(result.get("error", "read failed")), "error")

    elif tool_name == "search_dir":
        if result.get("success"):
            matches = result.get("matches", [])
            for match in matches[:8]:
                entry = Text(str(match), style=style("subtle"))
                entry.truncate(max(10, console.width - 8), overflow="ellipsis")
                console.print(
                    Text.assemble(
                        ("  " + GLYPHS["bullet"] + " ", style("accent_dim")),
                        entry,
                    )
                )
            if len(matches) > 8:
                console.print(
                    Text.assemble(
                        ("    ", ""),
                        (f"… and {len(matches) - 8} more", style("muted")),
                    )
                )
            _footer(
                [
                    (
                        plural(len(matches), "match", "matches"),
                        "success" if matches else "muted",
                    ),
                ]
                + ([("truncated", "warning")] if result.get("truncated") else [])
            )
        else:
            print_notice(str(result.get("error", "search failed")), "error")

    elif tool_name == "finish":
        message = str(result.get("message", "")).strip()
        if message:
            print_blank()
            print_assistant_header()
            render_markdown(message)

    else:
        if result.get("error"):
            print_notice(str(result["error"]), "error")
        elif result.get("success") is False:
            print_notice("action failed", "error")


def _print_bash_result(result: Dict[str, Any], duration_ms: Optional[float]) -> None:
    exit_code = int(result.get("exit_code", 0))
    stdout = str(result.get("stdout", "")).rstrip("\n")
    stderr = str(result.get("stderr", "")).rstrip("\n")
    ok = exit_code == 0

    stdout_lines = stdout.splitlines() if stdout else []
    stderr_lines = stderr.splitlines() if stderr else []

    if stdout_lines:
        _emit_log(stdout_lines, style("border"), style("text"))
    if stderr_lines:
        if stdout_lines:
            console.print(Text.assemble(("  " + GLYPHS["gutter"] + " ", style("border"))))
        _emit_log(stderr_lines, style("danger"), style("text"))

    combined = bool(stdout_lines or stderr_lines)

    parts: List[tuple] = [
        (f"exit {exit_code}", "success" if ok else "danger"),
    ]
    if duration_ms is not None:
        parts.append((format_duration(duration_ms), "muted"))
    if ok and not combined:
        parts.insert(0, ("no output", "muted"))
    _footer(parts)


# ---------------------------------------------------------------------------
# Markdown and chrome
# ---------------------------------------------------------------------------

def render_markdown(text: str) -> None:
    """Render Markdown with the interface's code theme."""
    if not text.strip():
        return
    console.print(Markdown(text, code_theme="github-dark", justify="left"))


def render_answer(text: str, meta: str = "") -> None:
    """Final answer block: heading, breathing room, Markdown."""
    body = text.strip()
    if not body:
        return
    print_blank()
    print_assistant_header(meta)
    console.print()
    render_markdown(body)


def render_opencode_footer() -> None:
    """The quiet key hint line under help screens."""
    hints = [
        ("tab", "mode"),
        ("/", "commands"),
        ("@", "files"),
        ("!", "shell"),
    ]
    line = Text("  ", style="")
    for index, (key, label) in enumerate(hints):
        if index:
            line.append("   " + GLYPHS["sep"] + "   ", style=style("border"))
        line.append(key, style=style("accent"))
        line.append(" " + label, style=style("muted"))
    console.print(line)
    console.print()
