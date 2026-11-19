"""
Autonomous ReAct (Reason + Act) loop and agent orchestration.
"""

import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from weblaptop.client import OllamaClient
from weblaptop.config import Config
from weblaptop.safety import ActionDecision, prompt_action_approval
from weblaptop.theme import PALETTE
from weblaptop.tools.registry import execute_tool
from weblaptop.ui import (
    console,
    print_notice,
    print_step_header,
    print_thought,
    print_tool_call,
    print_tool_result,
    render_answer,
)


SYSTEM_PROMPT = """You are weblaptop, a native autonomous terminal AI agent running on Arch Linux.
You solve coding, debugging, file manipulation, and system tasks autonomously in the terminal.

To accomplish tasks, follow the ReAct (Reasoning + Acting) loop:
1. First, reason about what to do in a "Thought:" block.
2. Next, if you need to take an action, output an "Action:" block with a valid JSON tool call.
3. If no action is needed, or once the task is finished, use the "finish" tool or output your final answer directly.

Supported Tools:
- run_bash: Execute a shell command in bash. Returns stdout, stderr, and exit_code.
  args: {"command": "string", "cwd": "string (optional)"}
- read_file: Read file contents from disk.
  args: {"path": "string"}
- write_file: Write or overwrite a file with content.
  args: {"path": "string", "content": "string"}
- search_dir: Search a directory recursively for files matching a pattern.
  args: {"path": "string (optional)", "pattern": "string (optional)"}
- finish: Complete the task and provide a final answer or summary.
  args: {"message": "string"}

Format Example:
Thought: I need to inspect the directory to locate the source code files.
Action:
```json
{
  "tool": "search_dir",
  "args": {
    "path": ".",
    "pattern": "*.c"
  }
}
```

Rules:
- Be direct, accurate, and concise.
- Always check files or compiler output before making assumptions.
- Run tests and verify your changes after editing code.
"""

EFFORT_GUIDELINES = {
    "off": "Reasoning Effort: OFF. Keep thoughts to a single concise sentence. Execute actions immediately without lengthy deliberation.",
    "low": "Reasoning Effort: LOW. Think briefly (1-2 sentences) in your Thought: section, focusing directly on the immediate next action.",
    "medium": "Reasoning Effort: MEDIUM. Think step-by-step. Clearly diagnose the issue or plan your action in your Thought: section before calling tools.",
    "high": "Reasoning Effort: HIGH. Think deeply and rigorously. Before taking action, thoroughly analyze the problem, consider edge cases, explore alternative hypotheses, and plan validation steps in your Thought: section.",
    "max": "Reasoning Effort: MAX. Maximum analytical depth. Carry out comprehensive reasoning: audit potential side-effects, verify syntax and logic, anticipate runtime errors, and plan thorough testing in your Thought: section before executing any action.",
}


def build_system_prompt(config: Config) -> str:
    """Generate system prompt customized with current reasoning effort guidelines."""
    effort_guideline = EFFORT_GUIDELINES.get(
        config.reasoning_effort, EFFORT_GUIDELINES["medium"]
    )
    return f"""{SYSTEM_PROMPT}

{effort_guideline}
"""


def _extract_json_objects(text: str) -> List[Dict[str, Any]]:
    """Robustly parse nested JSON objects from arbitrary text."""
    results = []
    start = 0
    text_len = len(text)
    while start < text_len:
        idx = text.find("{", start)
        if idx == -1:
            break
        depth = 0
        in_string = False
        escape = False
        end = -1
        for i in range(idx, text_len):
            c = text[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if not in_string:
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
        if end != -1:
            snippet = text[idx : end + 1]
            try:
                obj = json.loads(snippet)
                if isinstance(obj, dict):
                    results.append(obj)
            except Exception:
                pass
            start = idx + 1
        else:
            break
    return results


def extract_tool_call(text: str) -> Tuple[Optional[str], Optional[str], Optional[Dict[str, Any]]]:
    """
    Extract thought, tool name, and args from model output.
    Returns (thought, tool_name, args_dict).
    """
    thought = None
    tool_name = None
    args = None

    # Extract thought if labeled
    thought_match = re.search(r"Thought:\s*(.*?)(?=Action:|```|$)", text, re.DOTALL | re.IGNORECASE)
    if thought_match:
        thought = thought_match.group(1).strip()

    # Strategy 1: Look for ```json ... ``` code blocks
    json_blocks = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    for block in json_blocks:
        try:
            data = json.loads(block)
            if "tool" in data:
                tool_name = data.get("tool")
                args = data.get("args", {})
                break
            elif "name" in data:
                tool_name = data.get("name")
                args = data.get("parameters") or data.get("args", {})
                break
        except json.JSONDecodeError:
            continue

    # Strategy 2: Search for balanced JSON objects in text
    if not tool_name:
        objects = _extract_json_objects(text)
        for obj in objects:
            if "tool" in obj:
                tool_name = obj.get("tool")
                args = obj.get("args", {})
                break
            elif "name" in obj and ("parameters" in obj or "args" in obj):
                tool_name = obj.get("name")
                args = obj.get("parameters") or obj.get("args", {})
                break

    # Ensure args is a dictionary
    if args is None:
        args = {}

    return thought, tool_name, args


class Agent:
    """Autonomous ReAct agent loop."""

    def __init__(self, config: Config, client: OllamaClient):
        self.config = config
        self.client = client
        self.history: List[Dict[str, str]] = [
            {"role": "system", "content": build_system_prompt(config)}
        ]

    def update_system_prompt(self) -> None:
        """Synchronize system prompt with current config and reasoning effort."""
        new_prompt = build_system_prompt(self.config)
        if self.history and self.history[0]["role"] == "system":
            self.history[0]["content"] = new_prompt
        else:
            self.history.insert(0, {"role": "system", "content": new_prompt})

    def reset(self) -> None:
        """Reset conversation history to system prompt."""
        self.history = [{"role": "system", "content": build_system_prompt(self.config)}]

    def run_task(self, prompt: str) -> None:
        """
        Execute an autonomous task loop until finish or completion.
        """
        self.update_system_prompt()
        self.history.append({"role": "user", "content": prompt})
        step = 0

        while step < self.config.max_steps:
            step += 1
            print_step_header(step, self.config.max_steps)

            accumulated_response = ""
            started = time.monotonic()
            chunk_count = 0
            error_message: Optional[str] = None

            # Stream tokens from the model, showing a single live status line
            # instead of a silent pause.
            stream_gen = self.client.stream_chat(
                messages=self.history,
                model=self.config.model,
                temperature=self.config.effective_temperature,
            )

            with console.status(f"  [{PALETTE['muted']}]thinking…[/{PALETTE['muted']}]", spinner="dots") as status:
                for chunk in stream_gen:
                    if chunk.get("error"):
                        error_message = str(chunk["error"])
                        break

                    content_delta = chunk.get("content", "")
                    if content_delta:
                        accumulated_response += content_delta
                        chunk_count += 1
                        if chunk_count % 16 == 0:
                            status.update(
                                f"  [{PALETTE['muted']}]thinking · {time.monotonic() - started:.1f}s[/{PALETTE['muted']}]"
                            )

            if error_message:
                print_notice(f"model error: {error_message}", "error")
                return

            if not accumulated_response.strip():
                print_notice(
                    "empty response from model",
                    "warn",
                    detail="check the model name and server",
                )
                break

            # Parse ReAct components
            thought, tool_name, tool_args = extract_tool_call(accumulated_response)

            # Display thought if present
            if thought:
                print_thought(thought)

            # If no tool was called or model replied with conversational text
            if not tool_name:
                # Clean up any leftover Thought: tags for clean final display
                clean_response = re.sub(
                    r"Thought:\s*.*?(?=(?:\n\n|\Z))", "", accumulated_response, flags=re.DOTALL
                ).strip()
                if not clean_response:
                    clean_response = accumulated_response

                render_answer(clean_response, meta=self.config.model)
                self.history.append({"role": "assistant", "content": accumulated_response})
                break

            # Handle the "finish" tool
            if tool_name == "finish":
                final_msg = tool_args.get("message", "Task completed.")
                render_answer(final_msg, meta=self.config.model)
                self.history.append({"role": "assistant", "content": accumulated_response})
                break

            # Display planned tool action
            print_tool_call(tool_name, tool_args)

            # Safety check & confirmation gate
            decision, approved_args = prompt_action_approval(
                tool_name=tool_name,
                args=tool_args,
                config=self.config,
                console=console,
            )

            if decision == ActionDecision.DENIED:
                obs_content = f"Observation: Action '{tool_name}' was denied by user."
                self.history.append({"role": "assistant", "content": accumulated_response})
                self.history.append({"role": "user", "content": obs_content})
                continue

            # Execute tool
            execution_started = time.perf_counter()
            result = execute_tool(
                name=tool_name,
                args=approved_args,
                cwd=self.config.cwd,
            )
            duration_ms = (time.perf_counter() - execution_started) * 1000.0

            # Display execution result
            print_tool_result(tool_name, result, duration_ms=duration_ms, cwd=self.config.cwd)

            # Append observation to history for next ReAct cycle
            obs_json = json.dumps(result, ensure_ascii=False)
            self.history.append({"role": "assistant", "content": accumulated_response})
            self.history.append({"role": "user", "content": f"Observation: {obs_json}"})

        if step >= self.config.max_steps:
            print_notice(
                f"step limit reached ({self.config.max_steps})",
                "warn",
                detail="raise it with --max-steps or /config set max_steps <n>",
            )
