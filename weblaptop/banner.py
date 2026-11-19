"""
Header and status views for weblaptop.

The header is the only place the interface introduces itself: one wordmark
line with the connection state pushed to the right, then a quiet state line
with the model, directory, branch, and mode. No logo block, no rules, no
box. On narrow terminals the state line folds instead of wrapping.
"""

import os
import subprocess
from typing import List, Optional

from rich.console import Console
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from weblaptop import __version__
from weblaptop.config import Config
from weblaptop.theme import (
    COMPACT_WIDTH,
    GLYPHS,
    display_path,
    mid_truncate,
    style,
    truncate,
)


def get_git_info(cwd: str) -> str:
    """Extract current git branch or folder name."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return f"git:{proc.stdout.strip()}"
    except Exception:
        pass
    return os.path.basename(cwd) or "repo"


def generate_gradient(colors: List[str], steps: int) -> List[str]:
    """Compatibility helper for the test suite."""
    if steps <= 0:
        return []
    if steps == 1 or len(colors) == 1:
        return [colors[0].lower()] * steps
    return [colors[min(i * len(colors) // steps, len(colors) - 1)].lower() for i in range(steps)]


def render_logo(console: Console, style: str = "cyan") -> None:
    """Render the compact wordmark on its own."""
    console.print(
        Text.assemble(
            ("  ", ""),
            (GLYPHS["brand"], f"bold {style}"),
            ("  weblaptop", f"bold {style}"),
        )
    )


def _endpoint(config: Config) -> str:
    return config.server_url.replace("http://", "").replace("https://", "").rstrip("/")


def _status_text(
    ping_ms: Optional[float], is_online: bool, error_msg: Optional[str]
) -> Text:
    if is_online and ping_ms is not None:
        return Text.assemble(
            (GLYPHS["online"] + " ", style("success")),
            ("online", style("success")),
            (f"  {ping_ms:.0f} ms", style("muted")),
        )
    label = "offline"
    text = Text.assemble(
        (GLYPHS["offline"] + " ", style("danger")),
        (label, style("danger")),
    )
    if error_msg:
        text.append("  " + truncate(error_msg, 36), style=style("muted"))
    return text


def _mode_text(config: Config, hint: bool = False) -> Text:
    build = config.is_autonomous
    color = "success" if build else "warning"
    label = "BUILD" if build else "PLAN"
    target = "PLAN" if build else "BUILD"

    line = Text.assemble(
        (GLYPHS["bar"] + " ", f"bold {style(color)}"),
        (label, f"bold {style(color)}"),
    )
    if hint:
        line.append("   " + GLYPHS["sep"] + "   ", style=style("border"))
        line.append(f"tab switches to {target}", style=style("muted"))
    return line


def _identity() -> Text:
    return Text.assemble(
        ("  ", ""),
        (GLYPHS["brand"], f"bold {style('brand')}"),
        ("  weblaptop", f"bold {style('text')}"),
        (f"  {__version__}", style("muted")),
    )


def _segments(config: Config) -> List[Text]:
    """Build the state line in priority order."""
    cwd = display_path(config.cwd)
    branch = get_git_info(config.cwd)
    build = config.is_autonomous
    mode_color = "success" if build else "warning"

    return [
        Text(config.model, style=style("text")),
        Text(cwd, style=style("subtle")),
        Text(branch, style=style("muted")),
        Text(config.reasoning_effort, style=style("muted")),
        Text(config.mode.upper(), style=f"bold {style(mode_color)}"),
    ]


def _join_segments(segments: List[Text], width: int) -> Text:
    """Join as many segments as fit, always keeping model and mode."""
    if not segments:
        return Text()

    model, mode = segments[0], segments[-1]
    middles = segments[1:-1]

    def measure(parts: List[Text]) -> int:
        return sum(len(part.plain) for part in parts) + 3 * max(0, len(parts) - 1)

    chosen = [model, mode]
    for part in middles:
        if measure(chosen + [part]) <= width:
            chosen.insert(len(chosen) - 1, part)

    line = Text()
    for index, part in enumerate(chosen):
        if index:
            line.append(" " + GLYPHS["sep"] + " ", style=style("border"))
        line.append_text(part)
    return line


def render_status_line(
    console: Console,
    config: Config,
    ping_ms: Optional[float] = None,
    is_online: bool = False,
    error_msg: Optional[str] = None,
) -> None:
    """Render the startup header."""
    compact = console.width < COMPACT_WIDTH
    status = _status_text(ping_ms, is_online, error_msg)

    console.print()
    if compact:
        console.print(_identity())
        console.print(Text.assemble(("     ", ""), status))
        console.print(
            Text.assemble(
                ("     ", ""),
                (truncate(config.model, console.width - 7), style("text")),
            )
        )
        cwd = mid_truncate(display_path(config.cwd), max(12, console.width - 16))
        console.print(
            Text.assemble(
                ("     ", ""),
                (cwd, style("subtle")),
                (" " + GLYPHS["sep"] + " ", style("border")),
                (get_git_info(config.cwd), style("muted")),
            )
        )
        console.print(Text.assemble(("     ", ""), _mode_text(config)))
    else:
        top = Table.grid(expand=True, padding=0)
        top.add_column(justify="left", no_wrap=True)
        top.add_column(justify="right", no_wrap=True)
        top.add_row(_identity(), status)
        console.print(top)

        state = _join_segments(_segments(config), max(20, console.width - 7))
        console.print(Text.assemble(("     ", ""), state))
    console.print()

    if not is_online:
        hint = Text.assemble(
            ("  ", ""),
            (GLYPHS["warn"] + " ", f"bold {style('warning')}"),
            ("cannot reach ", style("text")),
            (_endpoint(config), style("subtle")),
        )
        if error_msg:
            hint.append("   " + truncate(error_msg, 48), style=style("muted"))
        hint.append("   try  --server <url>", style=style("muted"))
        console.print(hint)
        console.print()


def render_status_panel(
    console: Console,
    config: Config,
    ping_ms: Optional[float] = None,
    is_online: bool = False,
    error_msg: Optional[str] = None,
) -> None:
    """Detailed state view, used by `/status`."""
    console.print()
    console.print(
        Text.assemble(
            ("  ", ""),
            ("status", f"bold {style('brand')}"),
        )
    )

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style=style("muted"), no_wrap=True, min_width=10)
    grid.add_column()

    mode = _mode_text(config)
    mode.append(
        "   " + ("autonomous execution" if config.is_autonomous else "read-only planning"),
        style=style("subtle"),
    )

    grid.add_row("connection", _status_text(ping_ms, is_online, error_msg))
    grid.add_row("model", Text(config.model, style=style("text")))
    grid.add_row(
        "effort",
        Text.assemble(
            (config.reasoning_effort, style("text")),
            (f"  (temperature {config.effective_temperature:.2f})", style("muted")),
        ),
    )
    grid.add_row("mode", mode)
    grid.add_row("server", Text(_endpoint(config), style=style("text")))
    grid.add_row("directory", Text(display_path(config.cwd), style=style("text")))
    grid.add_row(
        "limits",
        Text.assemble(
            (f"{config.max_steps} steps", style("text")),
            (f"  {GLYPHS['sep']}  ", style("border")),
            (f"{config.timeout:.0f} s timeout", style("text")),
        ),
    )

    console.print(Padding(grid, (0, 0, 0, 4), expand=False))
    console.print()
