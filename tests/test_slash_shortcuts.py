"""
Unit tests for Antigravity-style slash shortcuts and configuration in weblaptop.
"""

import unittest
from unittest.mock import MagicMock
from prompt_toolkit.document import Document

from weblaptop.agent import Agent, build_system_prompt
from weblaptop.client import OllamaClient
from weblaptop.config import Config
from weblaptop.repl import (
    AntigravitySlashCompleter,
    handle_slash_command,
    handle_config_command,
)


class TestSlashShortcuts(unittest.TestCase):
    def setUp(self):
        self.config = Config(model="test-model:latest", reasoning_effort="medium")
        self.mock_client = MagicMock(spec=OllamaClient)
        self.mock_client.get_models.return_value = ["model-alpha:latest", "model-beta:latest"]
        self.mock_client.fetch_models.return_value = (
            ["model-alpha:latest", "model-beta:latest"],
            None,
        )
        self.agent = Agent(config=self.config, client=self.mock_client)
        self.completer = AntigravitySlashCompleter(get_models_cb=lambda: ["model-alpha", "model-beta"])

    def test_root_slash_completions(self):
        doc = Document("/")
        completions = list(self.completer.get_completions(doc, None))
        texts = [c.text for c in completions]
        self.assertIn("/model", texts)
        self.assertIn("/effort", texts)
        self.assertIn("/reasoning", texts)
        self.assertIn("/config", texts)
        self.assertIn("/yolo", texts)
        self.assertIn("/status", texts)
        self.assertIn("/history", texts)
        self.assertIn("/system", texts)

    def test_effort_sub_completions(self):
        doc = Document("/effort ")
        completions = list(self.completer.get_completions(doc, None))
        texts = [c.text for c in completions]
        self.assertEqual(texts, ["off", "low", "medium", "high", "max"])

    def test_model_sub_completions(self):
        doc = Document("/model ")
        completions = list(self.completer.get_completions(doc, None))
        texts = [c.text for c in completions]
        self.assertEqual(texts, ["model-alpha", "model-beta"])

    def test_config_sub_completions(self):
        doc = Document("/config ")
        completions = list(self.completer.get_completions(doc, None))
        texts = [c.text for c in completions]
        self.assertIn("show", texts)
        self.assertIn("set", texts)
        self.assertIn("reset", texts)

        doc_set = Document("/config set ")
        set_completions = list(self.completer.get_completions(doc_set, None))
        set_keys = [c.text for c in set_completions]
        self.assertIn("effort", set_keys)
        self.assertIn("model", set_keys)
        self.assertIn("temperature", set_keys)

    def test_handle_effort_command(self):
        handle_slash_command("/effort high", self.config, self.mock_client, self.agent)
        self.assertEqual(self.config.reasoning_effort, "high")
        self.assertEqual(self.config.effective_temperature, 0.5)
        # Ensure system prompt updated
        self.assertIn("Reasoning Effort: HIGH", self.agent.history[0]["content"])

    def test_handle_model_command(self):
        handle_slash_command("/model custom-coder:latest", self.config, self.mock_client, self.agent)
        self.assertEqual(self.config.model, "custom-coder:latest")

    def test_handle_config_set(self):
        handle_config_command(self.config, self.agent, "set max_steps 45")
        self.assertEqual(self.config.max_steps, 45)

        handle_config_command(self.config, self.agent, "set temperature 0.85")
        self.assertEqual(self.config.effective_temperature, 0.85)

        handle_config_command(self.config, self.agent, "set effort max")
        self.assertEqual(self.config.reasoning_effort, "max")

    def test_system_prompt_guidelines(self):
        self.config.reasoning_effort = "off"
        prompt_off = build_system_prompt(self.config)
        self.assertIn("Reasoning Effort: OFF", prompt_off)

        self.config.reasoning_effort = "max"
        prompt_max = build_system_prompt(self.config)
        self.assertIn("Reasoning Effort: MAX", prompt_max)


if __name__ == "__main__":
    unittest.main()
