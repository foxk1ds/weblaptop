"""
Mocked end-to-end ReAct loop tests for weblaptop agent.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock

from weblaptop.agent import Agent
from weblaptop.config import Config
from weblaptop.client import OllamaClient


class TestAgentLoop(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.cwd = self.temp_dir.name
        self.config = Config(yolo=True, cwd=self.cwd, max_steps=5)
        self.mock_client = MagicMock(spec=OllamaClient)
        self.agent = Agent(config=self.config, client=self.mock_client)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_react_loop_multi_turn(self):
        # Turn 1: Model decides to write a file
        turn1_response = """
Thought: I will write a C source file main.c.
Action:
```json
{
  "tool": "write_file",
  "args": {
    "path": "main.c",
    "content": "int main() { return 0; }"
  }
}
```
"""
        # Turn 2: Model verifies by reading the file
        turn2_response = """
Thought: Let me verify the file exists.
Action:
```json
{
  "tool": "read_file",
  "args": {
    "path": "main.c"
  }
}
```
"""
        # Turn 3: Model finishes
        turn3_response = """
Thought: The file is verified.
Action:
```json
{
  "tool": "finish",
  "args": {
    "message": "main.c has been created and verified successfully."
  }
}
```
"""

        # Set up mock stream_chat responses for the three turns
        def mock_stream(messages, model, temperature):
            # Pick response based on call count or messages length
            user_and_obs = [m for m in messages if m["role"] == "user"]
            if len(user_and_obs) == 1:
                yield {"content": turn1_response, "done": True}
            elif len(user_and_obs) == 2:
                yield {"content": turn2_response, "done": True}
            else:
                yield {"content": turn3_response, "done": True}

        self.mock_client.stream_chat.side_effect = mock_stream

        # Run task
        self.agent.run_task("Create and verify main.c")

        # Verify file actually created on disk
        target_file = os.path.join(self.cwd, "main.c")
        self.assertTrue(os.path.exists(target_file))
        with open(target_file) as f:
            self.assertEqual(f.read(), "int main() { return 0; }")

        # Verify history contains observations
        self.assertEqual(len(self.agent.history), 7)
        # [0]=system, [1]=user, [2]=turn1, [3]=obs1, [4]=turn2, [5]=obs2, [6]=turn3


if __name__ == "__main__":
    unittest.main()


    def test_react_loop_bash_execution(self):
        # Turn 1: Model compiles and runs a bash command
        turn1_response = """
Thought: Let's run a bash command to check the kernel architecture.
Action:
```json
{
  "tool": "run_bash",
  "args": {
    "command": "uname -m"
  }
}
```
"""
        # Turn 2: Finish
        turn2_response = """
Thought: Got the architecture.
Action:
```json
{
  "tool": "finish",
  "args": {
    "message": "Arch Linux system is running on the detected architecture."
  }
}
```
"""
        def mock_stream(messages, model, temperature):
            user_and_obs = [m for m in messages if m["role"] == "user"]
            if len(user_and_obs) == 1:
                yield {"content": turn1_response, "done": True}
            else:
                yield {"content": turn2_response, "done": True}

        self.mock_client.stream_chat.side_effect = mock_stream
        self.agent.run_task("Check architecture")

        # Verify observation from uname -m was recorded
        obs = self.agent.history[3]["content"]
        self.assertIn("Observation:", obs)
        self.assertIn("exit_code\": 0", obs)
