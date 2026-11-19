"""
Ollama HTTP API Client with streaming and latency measurement.
"""

import json
import socket
import time
from typing import Any, Dict, Generator, List, Optional, Tuple
import requests


class OllamaClient:
    """Client for PC's Ollama LLM Server over LAN."""

    def __init__(self, server_url: str = "http://192.168.100.106:11434", timeout: float = 60.0):
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout

    def ping(self, timeout: float = 2.0) -> Tuple[bool, Optional[float], Optional[str]]:
        """
        Measure ping latency to server via socket connect & HTTP probe.
        Returns (is_online, latency_ms, error_description).
        """
        host = self.server_url.replace("http://", "").replace("https://", "").split("/")[0]
        port = 11434
        if ":" in host:
            parts = host.split(":")
            host = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                port = 11434

        t0 = time.perf_counter()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            t1 = time.perf_counter()
            sock.close()
            latency_ms = (t1 - t0) * 1000.0
            return True, latency_ms, None
        except socket.timeout:
            return False, None, "Connection timed out"
        except ConnectionRefusedError:
            return False, None, "Connection refused (is Ollama running?)"
        except OSError as e:
            # Try HTTP request fallback in case raw socket is blocked or proxy used
            try:
                t0_http = time.perf_counter()
                resp = requests.get(f"{self.server_url}/api/version", timeout=timeout)
                t1_http = time.perf_counter()
                if resp.status_code == 200:
                    return True, (t1_http - t0_http) * 1000.0, None
            except Exception:
                pass
            return False, None, str(e)
        finally:
            try:
                sock.close()
            except Exception:
                pass

    @staticmethod
    def _ollama_names(data: Any) -> List[str]:
        """Extract model names from an Ollama /api/tags payload."""
        if not isinstance(data, dict):
            return []
        return [m["name"] for m in data.get("models", []) if m.get("name")]

    @staticmethod
    def _openai_names(data: Any) -> List[str]:
        """Extract model ids from an OpenAI-compatible /v1/models payload."""
        if not isinstance(data, dict):
            return []
        return [m["id"] for m in data.get("data", []) if m.get("id")]

    def fetch_models(self, timeout: float = 3.0) -> Tuple[List[str], Optional[str]]:
        """
        Ask the server which models it actually has.

        Tries Ollama's native /api/tags first, then the OpenAI-compatible
        /v1/models endpoint. Returns (models, error):
        - models present, error None: the server answered with a list
        - models empty, error None: the server answered but has no models
        - models empty, error set: no endpoint could be read

        Nothing is inferred or defaulted here; the list is whatever the
        server reported.
        """
        endpoints = (
            (f"{self.server_url}/api/tags", self._ollama_names),
            (f"{self.server_url}/v1/models", self._openai_names),
        )
        failures: List[str] = []
        answered_empty = False

        for url, parse in endpoints:
            try:
                resp = requests.get(url, timeout=timeout)
            except requests.exceptions.RequestException as exc:
                failures.append(f"{url}: {exc}")
                continue

            if resp.status_code != 200:
                failures.append(f"{url}: HTTP {resp.status_code}")
                continue

            try:
                data = resp.json()
            except ValueError:
                failures.append(f"{url}: response was not JSON")
                continue

            answered_empty = True
            models = parse(data)
            if models:
                # Preserve server order, drop duplicates.
                return list(dict.fromkeys(models)), None

        if answered_empty:
            return [], None
        return [], "; ".join(failures) or "no model endpoint answered"

    def get_models(self, timeout: float = 3.0) -> List[str]:
        """Fetch list of available models from the server."""
        return self.fetch_models(timeout=timeout)[0]

    def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: str,
        temperature: float = 0.2,
    ) -> Generator[Dict[str, Any], None, None]:
        """
        Stream chat completion from Ollama /api/chat.
        Yields chunk dicts containing 'content', 'done', and message details.
        """
        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature,
            },
        }

        url = f"{self.server_url}/api/chat"
        try:
            with requests.post(url, json=payload, stream=True, timeout=self.timeout) as resp:
                if resp.status_code != 200:
                    error_text = resp.text
                    yield {
                        "error": f"HTTP {resp.status_code}: {error_text}",
                        "done": True,
                        "content": "",
                    }
                    return

                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line.decode("utf-8"))
                        msg = chunk.get("message", {})
                        content = msg.get("content", "")
                        done = chunk.get("done", False)
                        yield {
                            "content": content,
                            "done": done,
                            "raw": chunk,
                        }
                        if done:
                            break
                    except json.JSONDecodeError:
                        continue
        except requests.exceptions.RequestException as e:
            yield {
                "error": f"Network error connecting to {url}: {e}",
                "done": True,
                "content": "",
            }
