"""
Native bash execution tool with safety and output limits.
"""

import os
import subprocess
from typing import Any, Dict, Optional


def run_bash(
    command: str,
    cwd: Optional[str] = None,
    timeout: float = 120.0,
    max_output_chars: int = 12000,
) -> Dict[str, Any]:
    """
    Execute a shell command inside bash and capture stdout, stderr, and exit code.
    """
    work_dir = os.path.abspath(os.path.expanduser(cwd)) if cwd else os.getcwd()
    if not os.path.isdir(work_dir):
        return {
            "command": command,
            "cwd": work_dir,
            "exit_code": 1,
            "stdout": "",
            "stderr": f"Error: Working directory does not exist: {work_dir}",
            "success": False,
        }

    try:
        proc = subprocess.run(
            ["/bin/bash", "-c", command],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )

        stdout = proc.stdout
        stderr = proc.stderr

        # Truncate output safely if too large to prevent overflowing LLM context window
        if len(stdout) > max_output_chars:
            head = stdout[: max_output_chars // 2]
            tail = stdout[-max_output_chars // 2 :]
            stdout = f"{head}\n\n... [Output truncated: {len(proc.stdout)} chars total] ...\n\n{tail}"

        if len(stderr) > max_output_chars:
            head = stderr[: max_output_chars // 2]
            tail = stderr[-max_output_chars // 2 :]
            stderr = f"{head}\n\n... [Stderr truncated: {len(proc.stderr)} chars total] ...\n\n{tail}"

        return {
            "command": command,
            "cwd": work_dir,
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "success": proc.returncode == 0,
        }

    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "cwd": work_dir,
            "exit_code": 124,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds.",
            "success": False,
        }
    except Exception as e:
        return {
            "command": command,
            "cwd": work_dir,
            "exit_code": 1,
            "stdout": "",
            "stderr": f"Execution failed: {e}",
            "success": False,
        }
