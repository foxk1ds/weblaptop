"""
Tool registry, schema definitions, and execution dispatcher.
"""

from typing import Any, Dict, List, Optional
from weblaptop.tools.bash import run_bash
from weblaptop.tools.filesystem import read_file, write_file, search_dir


TOOL_DEFINITIONS = [
    {
        "name": "run_bash",
        "description": "Execute a bash shell command in the environment and return exit code, stdout, and stderr.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash shell command to execute.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional directory to run the command in. Defaults to current directory.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a text file from the filesystem.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to read (relative or absolute).",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or overwrite content to a file. Automatically creates parent directories.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the destination file.",
                },
                "content": {
                    "type": "string",
                    "description": "Full text content to write into the file.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "search_dir",
        "description": "Search directory for files matching an optional pattern (glob or keyword).",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to search. Defaults to '.' (current directory).",
                },
                "pattern": {
                    "type": "string",
                    "description": "Optional glob or keyword to filter filenames (e.g. '*.c', 'Makefile', 'leak').",
                },
            },
            "required": [],
        },
    },
    {
        "name": "finish",
        "description": "Signal that the task is finished or provide the final conversational answer.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Summary of actions taken or final answer to the user.",
                },
            },
            "required": ["message"],
        },
    },
]


def execute_tool(name: str, args: Dict[str, Any], cwd: str) -> Dict[str, Any]:
    """Dispatch and execute tool by name with provided arguments."""
    try:
        if name == "run_bash":
            cmd = args.get("command", "")
            cmd_cwd = args.get("cwd") or cwd
            return run_bash(command=cmd, cwd=cmd_cwd)

        elif name == "read_file":
            path = args.get("path", "")
            return read_file(path=path, cwd=cwd)

        elif name == "write_file":
            path = args.get("path", "")
            content = args.get("content", "")
            return write_file(path=path, content=content, cwd=cwd)

        elif name == "search_dir":
            path = args.get("path", ".")
            pattern = args.get("pattern")
            return search_dir(path=path, pattern=pattern, cwd=cwd)

        elif name == "finish":
            return {
                "status": "completed",
                "message": args.get("message", "Task completed."),
                "success": True,
            }

        else:
            return {
                "error": f"Unknown tool: '{name}'. Available tools: run_bash, read_file, write_file, search_dir, finish.",
                "success": False,
            }
    except Exception as e:
        return {
            "error": f"Error executing tool '{name}': {e}",
            "success": False,
        }
