"""
Unit tests for OpenCode-style TUI features in weblaptop.
"""

import os
import tempfile
import unittest
from prompt_toolkit.document import Document

from weblaptop.config import Config
from weblaptop.repl import OpenCodeCompleter, resolve_file_references
from weblaptop.tools.filesystem import write_file


class TestOpenCodeFeatures(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cwd = self.temp_dir.name
        self.config = Config(cwd=self.cwd, mode="build")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_opencode_mode_toggle(self):
        self.assertEqual(self.config.mode, "build")
        self.assertTrue(self.config.is_autonomous)

        # Toggle to PLAN
        new_mode = self.config.toggle_mode()
        self.assertEqual(new_mode, "plan")
        self.assertFalse(self.config.is_autonomous)

        # Toggle back to BUILD
        new_mode2 = self.config.toggle_mode()
        self.assertEqual(new_mode2, "build")
        self.assertTrue(self.config.is_autonomous)

    def test_opencode_at_file_autocomplete(self):
        write_file("src/main.c", "int main() { return 0; }", cwd=self.cwd)
        write_file("README.md", "# Test Project", cwd=self.cwd)

        completer = OpenCodeCompleter(cwd_cb=lambda: self.cwd)
        doc = Document("review @main")
        completions = list(completer.get_completions(doc, None))
        texts = [c.text for c in completions]
        self.assertIn("@src/main.c", texts)

    def test_opencode_at_file_context_resolution(self):
        write_file("hello.txt", "Hello OpenCode World!", cwd=self.cwd)

        raw_prompt = "explain the greeting in @hello.txt"
        resolved = resolve_file_references(raw_prompt, cwd=self.cwd)

        self.assertIn("Content of @hello.txt:", resolved)
        self.assertIn("Hello OpenCode World!", resolved)
        self.assertIn("explain the greeting in @hello.txt", resolved)


if __name__ == "__main__":
    unittest.main()
