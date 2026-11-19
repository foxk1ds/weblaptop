"""
Interactive safety gate for mutating actions.

The approval card is the one place the interface deliberately blocks the
flow, so it is shaped differently from tool output: amber frame, the full
action, the exact target, and a single line of choices.
"""

import difflib
import os
import subprocess
import tempfile
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from prompt_toolkit import prompt as pt_prompt
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from weblaptop.config import Config
from weblaptop.theme import CARD, GLYPHS, display_path, style


class ActionDecision(Enum):
    APPROVED = "approved"
    DENIED = "denied"
    EDITED = "edited"
    AUTO_APPROVE = "auto_approve"


def _generate_diff(existing_path: str, new_content: str) -> Optional[str]:
    """Generate unified diff between existing file content and proposed new content."""
    try:
        if not os.path.exists(existing_path):
            return None
        with open(existing_path, "r", encoding="utf-8", errors="replace") as f:
            old_content = f.read()
        diff = difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{os.path.basename(existing_path)}",
            tofile=f"b/{os.path.basename(existing_path)}",
            n=3,
        )
        diff_str = "".join(diff)
        return diff_str if diff_str.strip() else "(No textual changes)"
    except Exception:
        return None


def _clip_diff(diff_str: str, limit: int = 28) -> str:
    """Keep a reviewable diff on screen; the editor holds the full content."""
    lines = diff_str.splitlines()
    if len(lines) <= limit:
        return diff_str
    head = max(1, (limit * 2) // 3)
    tail = max(1, limit - head)
    omitted = len(lines) - limit
    marker = f"... [{omitted} diff lines omitted · choose e to edit] ..."
    return "\n".join(lines[:head] + [marker] + lines[-tail:])


def _diff_stats(diff_str: Optional[str]) -> Tuple[int, int]:
    if not diff_str:
        return 0, 0
    added = removed = 0
    for line in diff_str.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


def _edit_via_external_editor(initial_content: str, suffix: str = ".txt") -> str:
    """Open user's $EDITOR to let them edit file content interactively."""
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "nano"
    with tempfile.NamedTemporaryFile(mode="w+", suffix=suffix, delete=False, encoding="utf-8") as tf:
        tf.write(initial_content)
        tf_name = tf.name

    try:
        subprocess.run([editor, tf_name], check=True)
        with open(tf_name, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return initial_content
    finally:
        try:
            os.remove(tf_name)
        except OSError:
            pass


def _choices_line() -> Text:
    line = Text("  ", style="")
    choices = [
        ("y", "approve", "success"),
        ("n", "deny", "danger"),
        ("e", "edit", "accent"),
        ("a", "always", "warning"),
    ]
    for index, (key, label, color) in enumerate(choices):
        if index:
            line.append("   ", style="")
        line.append(key, style=f"bold {style(color)}")
        line.append(" " + label, style=style("subtle"))
    return line


def prompt_action_approval(
    tool_name: str,
    args: Dict[str, Any],
    config: Config,
    console: Console,
) -> Tuple[ActionDecision, Dict[str, Any]]:
    """
    Evaluate whether an action requires confirmation.
    By default prompts for run_bash and write_file unless config.yolo is True.
    """
    # In autonomous (BUILD / YOLO) mode, bypass all prompts without noise.
    if config.is_autonomous:
        return ActionDecision.APPROVED, args

    # Safe / read-only tools never prompt.
    if tool_name not in ("run_bash", "write_file"):
        return ActionDecision.APPROVED, args

    updated_args = dict(args)

    if tool_name == "run_bash":
        command = args.get("command", "")
        cwd = display_path(args.get("cwd") or config.cwd)
        console.print(
            Panel(
                Syntax(command, "bash", theme="github-dark", line_numbers=False),
                title="[bold]Approve command[/bold]",
                title_align="left",
                subtitle=f"[dim]{display_path(cwd)}[/dim]",
                subtitle_align="right",
                border_style=style("warning"),
                box=CARD,
                padding=(0, 1),
            )
        )

    elif tool_name == "write_file":
        path = args.get("path", "")
        content = args.get("content", "")
        full_path = path if os.path.isabs(path) else os.path.join(config.cwd, path)
        diff_str = _generate_diff(full_path, content)

        if diff_str and diff_str != "(No textual changes)":
            added, removed = _diff_stats(diff_str)
            body = Syntax(_clip_diff(diff_str), "diff", theme="github-dark", line_numbers=False)
            subtitle = f"[dim]{path}  ·  +{added} −{removed}[/dim]"
        else:
            lines = content.splitlines()
            preview_lines = lines[:20]
            preview = "\n".join(preview_lines)
            if len(lines) > 20:
                preview += f"\n... [{len(lines) - 20} more lines] ..."
            body = Syntax(preview, "text", theme="github-dark", line_numbers=False)
            subtitle = f"[dim]{path}  ·  new file, {len(content.encode('utf-8'))} bytes[/dim]"

        console.print(
            Panel(
                body,
                title="[bold]Approve write[/bold]",
                title_align="left",
                subtitle=subtitle,
                subtitle_align="right",
                border_style=style("warning"),
                box=CARD,
                padding=(0, 1),
            )
        )

    console.print(_choices_line())

    while True:
        try:
            choice = (
                console.input("  [bold #cdd6f4]approve[/]  [#89b4fa]›[/] ")
                .strip()
                .lower()
            )
        except (KeyboardInterrupt, EOFError):
            console.print()
            console.print(
                Text.assemble(
                    ("  " + GLYPHS["cross"] + " ", f"bold {style('danger')}"),
                    ("action aborted", style("text")),
                )
            )
            return ActionDecision.DENIED, args

        if choice in ("y", "yes", ""):
            return ActionDecision.APPROVED, updated_args

        elif choice in ("n", "no"):
            console.print(
                Text.assemble(
                    ("  " + GLYPHS["cross"] + " ", f"bold {style('danger')}"),
                    ("action denied", style("text")),
                )
            )
            return ActionDecision.DENIED, updated_args

        elif choice in ("a", "auto", "yolo", "always"):
            config.yolo = True
            config.mode = "build"
            console.print(
                Text.assemble(
                    ("  " + GLYPHS["check"] + " ", f"bold {style('success')}"),
                    ("BUILD mode for this session", style("text")),
                    ("   " + GLYPHS["sep"] + "   no more approvals", style("muted")),
                )
            )
            return ActionDecision.AUTO_APPROVE, updated_args

        elif choice in ("e", "edit"):
            if tool_name == "run_bash":
                edited_cmd = pt_prompt(
                    "edit bash command: ",
                    default=updated_args.get("command", ""),
                )
                updated_args["command"] = edited_cmd
                return ActionDecision.EDITED, updated_args

            elif tool_name == "write_file":
                edited_content = _edit_via_external_editor(
                    updated_args.get("content", ""),
                    suffix=os.path.splitext(updated_args.get("path", ""))[1] or ".txt",
                )
                updated_args["content"] = edited_content
                return ActionDecision.EDITED, updated_args

        else:
            console.print(
                Text.assemble(
                    ("  ", ""),
                    ("choose ", style("muted")),
                    ("y", style("success")),
                    (" / ", style("muted")),
                    ("n", style("danger")),
                    (" / ", style("muted")),
                    ("e", style("accent")),
                    (" / ", style("muted")),
                    ("a", style("warning")),
                )
            )
