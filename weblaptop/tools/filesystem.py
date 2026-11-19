"""
Filesystem tools: read_file, write_file, search_dir.
"""

import fnmatch
import os
from typing import Any, Dict, List, Optional


EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".cache",
    ".idea",
    ".vscode",
    "build",
    "dist",
}


def read_file(
    path: str,
    cwd: Optional[str] = None,
    max_lines: int = 2000,
    max_bytes: int = 200_000,
) -> Dict[str, Any]:
    """
    Read the contents of a file at the specified path.
    """
    base_dir = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
    full_path = (
        path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
    )

    if not os.path.exists(full_path):
        return {
            "path": full_path,
            "error": f"File not found: {path}",
            "success": False,
        }

    if os.path.isdir(full_path):
        return {
            "path": full_path,
            "error": f"Path is a directory, not a file: {path}. Use search_dir to explore directories.",
            "success": False,
        }

    try:
        size = os.path.getsize(full_path)
        with open(full_path, "rb") as f:
            sample = f.read(1024)
            if b"\x00" in sample:
                return {
                    "path": full_path,
                    "error": f"Binary file detected ({size} bytes). Cannot read as text.",
                    "success": False,
                }
            f.seek(0)
            raw_bytes = f.read(max_bytes + 1)
            content = raw_bytes[:max_bytes].decode("utf-8", errors="replace")

        lines = content.splitlines()
        truncated = False
        if len(lines) > max_lines or len(raw_bytes) > max_bytes:
            truncated = True
            lines = lines[:max_lines]
            content = "\n".join(lines) + f"\n\n... [Truncated: showing first {max_lines} lines of {path}] ..."

        return {
            "path": full_path,
            "content": content,
            "total_lines": len(lines),
            "size_bytes": size,
            "truncated": truncated,
            "success": True,
        }

    except Exception as e:
        return {
            "path": full_path,
            "error": f"Failed to read file: {e}",
            "success": False,
        }


def write_file(
    path: str,
    content: str,
    cwd: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Write or overwrite content to a file at the specified path.
    Creates parent directories automatically if they do not exist.
    """
    base_dir = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
    full_path = (
        path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
    )

    try:
        parent_dir = os.path.dirname(full_path)
        if parent_dir and not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)

        existed_before = os.path.exists(full_path)
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)

        encoded = content.encode("utf-8")
        return {
            "path": full_path,
            "bytes_written": len(encoded),
            "lines_written": len(content.splitlines()),
            "status": "updated" if existed_before else "created",
            "success": True,
        }

    except Exception as e:
        return {
            "path": full_path,
            "error": f"Failed to write file: {e}",
            "success": False,
        }


def search_dir(
    path: str = ".",
    pattern: Optional[str] = None,
    cwd: Optional[str] = None,
    max_results: int = 150,
) -> Dict[str, Any]:
    """
    Recursively search for files in a directory matching an optional glob or substring pattern.
    """
    base_dir = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
    target_dir = (
        path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))
    )

    if not os.path.exists(target_dir):
        return {
            "path": target_dir,
            "error": f"Directory not found: {path}",
            "matches": [],
            "success": False,
        }

    matches: List[str] = []
    try:
        for root, dirs, files in os.walk(target_dir):
            # Prune unwanted directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith(".")]

            for name in files:
                if len(matches) >= max_results:
                    break

                rel_path = os.path.relpath(os.path.join(root, name), base_dir)

                if pattern:
                    # Match via fnmatch glob or substring
                    if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(rel_path, pattern) or pattern.lower() in rel_path.lower():
                        matches.append(rel_path)
                else:
                    matches.append(rel_path)

            if len(matches) >= max_results:
                break

        return {
            "path": target_dir,
            "pattern": pattern,
            "matches": sorted(matches),
            "count": len(matches),
            "truncated": len(matches) >= max_results,
            "success": True,
        }

    except Exception as e:
        return {
            "path": target_dir,
            "error": f"Search failed: {e}",
            "matches": [],
            "success": False,
        }
