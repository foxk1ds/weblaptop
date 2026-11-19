"""
Rendering tests for the weblaptop interface.

These stay colour-free and width-pinned so they assert layout, not ANSI
escape sequences: alignment, truncation, plural forms, and the adaptive
header.
"""

import io
import tempfile
import unittest
from unittest.mock import patch

from rich.console import Console

import weblaptop.repl as repl
import weblaptop.ui as ui
from weblaptop.banner import render_status_line, render_status_panel
from weblaptop.config import Config
from weblaptop.theme import format_bytes, format_duration, plural


def make_console(width: int = 90):
    stream = io.StringIO()
    console = Console(file=stream, width=width, color_system=None)
    return console, stream


class TestThemeHelpers(unittest.TestCase):
    def test_plural(self):
        self.assertEqual(plural(1, "line"), "1 line")
        self.assertEqual(plural(2, "line"), "2 lines")
        self.assertEqual(plural(1, "match", "matches"), "1 match")
        self.assertEqual(plural(4, "match", "matches"), "4 matches")

    def test_durations(self):
        self.assertEqual(format_duration(52), "52 ms")
        self.assertEqual(format_duration(1210), "1.21 s")

    def test_bytes(self):
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(4096), "4.0 KB")


class TestHeader(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.config = Config(
            cwd=self.temp_dir.name,
            model="qwen2.5-coder:latest",
            mode="plan",
        )

    def test_full_header_has_identity_and_state(self):
        console, stream = make_console(96)
        render_status_line(console, self.config, ping_ms=4.2, is_online=True)
        out = stream.getvalue()

        for expected in ("weblaptop", "0.1.0", "qwen2.5-coder:latest", "PLAN", "online", "4 ms"):
            self.assertIn(expected, out)
        self.assertIn("♪", out)
        for line in out.splitlines():
            self.assertLessEqual(len(line), 96)

    def test_narrow_header_drops_the_hint_and_keeps_state(self):
        console, stream = make_console(58)
        render_status_line(console, self.config, ping_ms=4.2, is_online=True)
        out = stream.getvalue()

        self.assertIn("weblaptop", out)
        self.assertIn("online", out)
        self.assertIn("qwen2.5-coder:latest", out)
        self.assertNotIn("tab switches", out)
        for line in out.splitlines():
            self.assertLessEqual(len(line), 58)

    def test_status_panel_lists_connection_state(self):
        console, stream = make_console(90)
        render_status_panel(console, self.config, ping_ms=3.0, is_online=True)
        out = stream.getvalue()

        self.assertIn("status", out)
        self.assertIn("connection", out)
        self.assertIn("read-only planning", out)


class TestToolOutput(unittest.TestCase):
    def setUp(self):
        self.console, self.stream = make_console(80)
        self.patches = [
            patch("weblaptop.ui.console", self.console),
            patch("weblaptop.repl.console", self.console),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    def output(self):
        return self.stream.getvalue()

    def test_action_line_never_overflows(self):
        ui.print_tool_call(
            "run_bash",
            {"command": "x" * 400, "cwd": "/home/foxkids/weblaptop"},
        )
        out = self.output()
        self.assertIn("Bash", out)
        self.assertIn("…", out)
        for line in out.splitlines():
            self.assertLessEqual(len(line), 80)

    def test_bash_result_keeps_both_streams_and_outcome(self):
        ui.print_tool_result(
            "run_bash",
            {"exit_code": 1, "stdout": "building", "stderr": "error: expected ';'"},
            duration_ms=12,
        )
        out = self.output()
        self.assertIn("building", out)
        self.assertIn("error: expected ';'", out)
        self.assertIn("exit 1", out)
        self.assertIn("12 ms", out)

    def test_bash_result_reports_empty_output(self):
        ui.print_tool_result(
            "run_bash",
            {"exit_code": 0, "stdout": "", "stderr": ""},
            duration_ms=3,
        )
        self.assertIn("no output", self.output())

    def test_write_result_uses_singular_units(self):
        ui.print_tool_result(
            "write_file",
            {
                "success": True,
                "path": "main.c",
                "status": "created",
                "lines_written": 1,
                "bytes_written": 24,
            },
        )
        out = self.output()
        self.assertIn("1 line", out)
        self.assertNotIn("1 lines", out)

    def test_long_output_is_clipped_in_the_middle(self):
        stdout = "\n".join(f"line {index}" for index in range(60))
        ui.print_tool_result("run_bash", {"exit_code": 0, "stdout": stdout}, duration_ms=8)
        out = self.output()

        self.assertIn("line 0", out)
        self.assertIn("line 59", out)
        self.assertIn("lines omitted", out)
        self.assertNotIn("line 30", out)

    def test_answer_renders_under_a_heading(self):
        ui.render_answer("Done. The build passes.", meta="test-model")
        out = self.output()
        self.assertIn("weblaptop", out)
        self.assertIn("test-model", out)
        self.assertIn("The build passes.", out)


if __name__ == "__main__":
    unittest.main()
