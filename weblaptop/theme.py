"""
Design system for weblaptop's terminal interface.

One palette, one glyph set, one spacing rhythm. Every renderer imports from
here so the interface stays coherent as features are added.

The rules are deliberately narrow: a neutral text ramp carries almost all
content, a single blue accent marks actions and focus, and the three
semantic colours are reserved for success, warnings, and failure. Nothing
is boxed unless it needs to interrupt the user.
"""

import os
from typing import List

from rich import box


# Catppuccin Mocha, reduced to the roles the interface actually uses.
PALETTE = {
    "brand": "#89b4fa",      # blue: wordmark, actions, focus
    "accent": "#89b4fa",
    "accent_dim": "#5e81ac",
    "success": "#a6e3a1",
    "warning": "#f9e2af",
    "danger": "#f38ba8",
    "text": "#cdd6f4",
    "subtle": "#a6adc8",
    "muted": "#6c7086",
    "border": "#313244",
    "surface": "#181825",
}

GLYPHS = {
    "brand": "♪",
    "bar": "▌",
    "arrow": "❯",
    "action": "▸",
    "bullet": "·",
    "sep": "·",
    "online": "●",
    "offline": "○",
    "check": "✓",
    "cross": "✗",
    "warn": "!",
    "gutter": "│",
    "corner": "╰",
    "thought": "▎",
}

# Rounded corners everywhere: the only border style used.
CARD = box.ROUNDED

# Below this width the header drops its columns instead of wrapping them.
COMPACT_WIDTH = 74


def style(key: str) -> str:
    """Return a palette colour by name (falls back to body text)."""
    return PALETTE.get(key, PALETTE["text"])


def bold(key: str) -> str:
    """Return a bold palette style by name."""
    return f"bold {style(key)}"


def display_path(path: str) -> str:
    """Shorten the user's home directory to `~` for display."""
    home = os.path.expanduser("~")
    try:
        if path == home:
            return "~"
        if path.startswith(home + os.sep):
            return "~" + path[len(home):]
    except Exception:
        pass
    return path


def short_path(path: str, cwd: str = "") -> str:
    """Prefer a working-directory-relative path for result lines."""
    if not path:
        return ""
    if cwd:
        try:
            relative = os.path.relpath(path, cwd)
            if not relative.startswith(".."):
                return relative
        except Exception:
            pass
    return display_path(path)


def truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """Clip from the right, keeping a single visible ellipsis."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return ellipsis
    return text[: width - 1] + ellipsis


def mid_truncate(text: str, width: int, ellipsis: str = "…") -> str:
    """Keep both ends of a path or command, clipping the middle."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 3:
        return truncate(text, width, ellipsis)
    head = (width - 1) // 2
    tail = width - 1 - head
    return text[:head] + ellipsis + text[-tail:]


def format_duration(ms: float) -> str:
    """Human-readable duration from milliseconds."""
    if ms < 1000:
        return f"{ms:.0f} ms"
    return f"{ms / 1000:.2f} s"


def format_bytes(count: int) -> str:
    """Human-readable byte count."""
    value = float(count)
    if value < 1024:
        return f"{int(value)} B"
    for unit in ("KB", "MB", "GB"):
        value /= 1024.0
        if value < 1024:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


def plural(count: int, singular: str, plural_form: str = "") -> str:
    """`1 line` / `3 lines`, with an optional irregular plural."""
    word = singular if count == 1 else (plural_form or singular + "s")
    return f"{count} {word}"


def split_log(lines: List[str], limit: int) -> List[str]:
    """
    Keep the useful parts of a long log: the head and the tail, with a
    single None marker standing in for everything that was dropped.
    """
    if len(lines) <= limit:
        return list(lines)
    head = max(1, (limit * 2) // 3)
    tail = max(1, limit - head)
    return list(lines[:head]) + [None] + list(lines[-tail:])
