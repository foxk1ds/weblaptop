"""Tests for authoritative model discovery (no guessed model names)."""

import unittest
from unittest.mock import MagicMock, patch

from weblaptop.client import OllamaClient


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class TestFetchModels(unittest.TestCase):
    def setUp(self):
        self.client = OllamaClient(server_url="http://192.168.100.106:11434")

    @patch("weblaptop.client.requests.get")
    def test_reads_ollama_tags(self, get):
        get.return_value = FakeResponse(payload={"models": [{"name": "qwen2.5:7b"}]})
        models, error = self.client.fetch_models()
        self.assertEqual(models, ["qwen2.5:7b"])
        self.assertIsNone(error)

    @patch("weblaptop.client.requests.get")
    def test_falls_back_to_openai_models(self, get):
        get.side_effect = [
            FakeResponse(payload={"models": []}),
            FakeResponse(payload={"data": [{"id": "qwen2.5:7b"}]}),
        ]
        models, error = self.client.fetch_models()
        self.assertEqual(models, ["qwen2.5:7b"])
        self.assertIsNone(error)

    @patch("weblaptop.client.requests.get")
    def test_empty_server_is_not_an_error(self, get):
        get.return_value = FakeResponse(payload={"models": []})
        models, error = self.client.fetch_models()
        self.assertEqual(models, [])
        self.assertIsNone(error)

    @patch("weblaptop.client.requests.get")
    def test_unreachable_server_reports_error(self, get):
        import requests

        get.side_effect = requests.exceptions.ConnectionError("refused")
        models, error = self.client.fetch_models()
        self.assertEqual(models, [])
        self.assertIn("refused", error)

    @patch("weblaptop.client.requests.get")
    def test_duplicates_are_dropped(self, get):
        get.return_value = FakeResponse(
            payload={"models": [{"name": "b:1"}, {"name": "a:1"}, {"name": "b:1"}]}
        )
        models, _ = self.client.fetch_models()
        self.assertEqual(models, ["b:1", "a:1"])

    @patch("weblaptop.client.requests.get")
    def test_get_models_still_returns_a_plain_list(self, get):
        get.return_value = FakeResponse(payload={"models": [{"name": "x:1"}]})
        self.assertEqual(self.client.get_models(), ["x:1"])


class TestListServerModels(unittest.TestCase):
    def test_lists_exact_models(self):
        from weblaptop.cli import list_server_models
        from weblaptop.config import Config

        config = Config(server_url="http://remote:11434", model="qwen2.5:7b")
        client = MagicMock()
        client.ping.return_value = (True, 3.0, None)
        client.fetch_models.return_value = (["qwen2.5:7b"], None)

        self.assertEqual(list_server_models(config, client), 0)

    def test_no_models_exits_nonzero(self):
        from weblaptop.cli import list_server_models
        from weblaptop.config import Config

        config = Config(server_url="http://remote:11434")
        client = MagicMock()
        client.ping.return_value = (True, 3.0, None)
        client.fetch_models.return_value = ([], None)

        self.assertEqual(list_server_models(config, client), 1)

    def test_offline_exits_nonzero(self):
        from weblaptop.cli import list_server_models
        from weblaptop.config import Config

        config = Config(server_url="http://remote:11434")
        client = MagicMock()
        client.ping.return_value = (False, None, "timed out")

        self.assertEqual(list_server_models(config, client), 1)


if __name__ == "__main__":
    unittest.main()
