"""
Unit tests for weblaptop agent and tools.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from weblaptop.agent import extract_tool_call, Agent
from weblaptop.banner import generate_gradient, render_logo, render_status_line
from weblaptop.client import OllamaClient
from weblaptop.config import Config
from weblaptop.safety import ActionDecision, prompt_action_approval
from weblaptop.tools.bash import run_bash
from weblaptop.tools.filesystem import read_file, write_file, search_dir
from weblaptop.tools.registry import execute_tool
from weblaptop.ui import console


class TestTools(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cwd = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_bash_success(self):
        res = run_bash("echo 'hello from arch'", cwd=self.cwd)
        self.assertTrue(res["success"])
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("hello from arch", res["stdout"])

    def test_run_bash_failure(self):
        res = run_bash("false", cwd=self.cwd)
        self.assertFalse(res["success"])
        self.assertEqual(res["exit_code"], 1)

    def test_write_and_read_file(self):
        test_path = "sub/dir/test.txt"
        test_content = "Hello, Arch Linux!\nLine 2"

        # Write
        w_res = write_file(test_path, test_content, cwd=self.cwd)
        self.assertTrue(w_res["success"])
        self.assertEqual(w_res["lines_written"], 2)

        # Read
        r_res = read_file(test_path, cwd=self.cwd)
        self.assertTrue(r_res["success"])
        self.assertEqual(r_res["content"], test_content)
        self.assertEqual(r_res["total_lines"], 2)

    def test_read_nonexistent_file(self):
        res = read_file("nonexistent.txt", cwd=self.cwd)
        self.assertFalse(res["success"])
        self.assertIn("File not found", res["error"])

    def test_search_dir(self):
        write_file("src/main.c", "int main() { return 0; }", cwd=self.cwd)
        write_file("src/util.h", "#define UTIL 1", cwd=self.cwd)
        write_file("README.md", "# Docs", cwd=self.cwd)

        # Search *.c
        res = search_dir(".", pattern="*.c", cwd=self.cwd)
        self.assertTrue(res["success"])
        self.assertEqual(res["count"], 1)
        self.assertIn("src/main.c", res["matches"])

        # Search all
        res_all = search_dir(".", cwd=self.cwd)
        self.assertEqual(res_all["count"], 3)

    def test_execute_tool_registry(self):
        res = execute_tool("run_bash", {"command": "echo 'ok'"}, cwd=self.cwd)
        self.assertTrue(res["success"])
        self.assertIn("ok", res["stdout"])

        res_unknown = execute_tool("fake_tool", {}, cwd=self.cwd)
        self.assertFalse(res_unknown["success"])
        self.assertIn("Unknown tool", res_unknown["error"])


class TestParser(unittest.TestCase):
    def test_extract_tool_call_json_block(self):
        sample = """
Thought: Let's compile main.c and test for memory leaks.
Action:
```json
{
  "tool": "run_bash",
  "args": {
    "command": "gcc -Wall main.c -o main && ./main"
  }
}
```
        """
        thought, tool, args = extract_tool_call(sample)
        self.assertIn("compile main.c", thought)
        self.assertEqual(tool, "run_bash")
        self.assertEqual(args["command"], "gcc -Wall main.c -o main && ./main")

    def test_extract_tool_call_raw_json(self):
        sample = """
Thought: I need to read the header file.
{"tool": "read_file", "args": {"path": "main.h"}}
        """
        thought, tool, args = extract_tool_call(sample)
        self.assertEqual(tool, "read_file")
        self.assertEqual(args["path"], "main.h")

    def test_conversational_response(self):
        sample = "Here is an explanation of the memory leak in your code. No tools needed."
        thought, tool, args = extract_tool_call(sample)
        self.assertIsNone(tool)


class TestSafety(unittest.TestCase):
    def test_yolo_mode_auto_approves(self):
        config = Config(yolo=True)
        decision, args = prompt_action_approval("run_bash", {"command": "rm -rf /tmp/test"}, config, console)
        self.assertEqual(decision, ActionDecision.APPROVED)

    def test_read_only_tools_auto_approved(self):
        config = Config(yolo=False)
        decision, args = prompt_action_approval("read_file", {"path": "main.c"}, config, console)
        self.assertEqual(decision, ActionDecision.APPROVED)


class TestBanner(unittest.TestCase):
    def test_gradient_generation(self):
        colors = ["#000000", "#FFFFFF"]
        grad = generate_gradient(colors, 10)
        self.assertEqual(len(grad), 10)
        self.assertEqual(grad[0], "#000000")
        self.assertEqual(grad[-1], "#ffffff")


if __name__ == "__main__":
    unittest.main()
