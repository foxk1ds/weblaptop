import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

VALID_EFFORTS = ("off", "low", "medium", "high", "max")
VALID_MODES = ("build", "plan")


@dataclass
class Config:
    """Runtime configuration for weblaptop agent in OpenCode style."""

    server_url: str = field(
        default_factory=lambda: os.getenv("WEBLAPTOP_SERVER", "http://192.168.100.106:11434")
    )
    model: str = field(
        default_factory=lambda: os.getenv("WEBLAPTOP_MODEL", "qwen2.5:7b")
    )
    reasoning_effort: str = field(
        default_factory=lambda: os.getenv("WEBLAPTOP_EFFORT", "medium").lower()
    )
    mode: str = "build"  # OpenCode modes: "build" (autonomous execution) vs "plan" (safe/analysis)
    yolo: bool = False
    cwd: str = field(default_factory=os.getcwd)
    timeout: float = 60.0
    max_steps: int = 30
    temperature: Optional[float] = None  # None = dynamically inferred from effort

    def __post_init__(self):
        # Sync yolo flag with build mode if yolo was explicitly enabled
        if self.yolo:
            self.mode = "build"

    @property
    def is_autonomous(self) -> bool:
        """Whether agent runs autonomously without action approval."""
        return self.yolo or self.mode.lower() == "build"

    def toggle_mode(self) -> str:
        """Toggle between OpenCode 'build' and 'plan' modes."""
        if self.is_autonomous:
            self.mode = "plan"
            self.yolo = False
        else:
            self.mode = "build"
            self.yolo = True
        return self.mode

    @property
    def effective_temperature(self) -> float:
        """Return temperature based on explicit setting or reasoning effort."""
        if self.temperature is not None:
            return self.temperature
        effort_map = {
            "off": 0.1,
            "low": 0.2,
            "medium": 0.3,
            "high": 0.5,
            "max": 0.7,
        }
        return effort_map.get(self.reasoning_effort, 0.3)

    @property
    def host(self) -> str:
        """Extract host/IP from server_url."""
        url = self.server_url.replace("http://", "").replace("https://", "")
        return url.split(":")[0].split("/")[0]

    @property
    def port(self) -> int:
        """Extract port from server_url, defaulting to 11434 for Ollama."""
        url = self.server_url.replace("http://", "").replace("https://", "")
        parts = url.split(":")
        if len(parts) > 1:
            try:
                return int(parts[1].split("/")[0])
            except ValueError:
                pass
        return 11434

    def set_value(self, key: str, val_str: str) -> Tuple[bool, str]:
        """Dynamically update a configuration key from user input string."""
        k = key.lower().strip()
        v = val_str.strip()

        if k in ("mode",):
            if v.lower() not in VALID_MODES:
                return False, f"Invalid mode '{v}'. Must be 'build' or 'plan'"
            self.mode = v.lower()
            self.yolo = self.mode == "build"
            return True, f"mode set to {self.mode.upper()}"

        elif k in ("server", "server_url"):
            if not v.startswith("http://") and not v.startswith("https://"):
                v = f"http://{v}"
            self.server_url = v
            return True, f"server_url set to {self.server_url}"

        elif k in ("model", "m"):
            self.model = v
            return True, f"model set to {self.model}"

        elif k in ("effort", "reasoning", "reasoning_effort"):
            if v.lower() not in VALID_EFFORTS:
                return False, f"Invalid effort '{v}'. Must be one of: {', '.join(VALID_EFFORTS)}"
            self.reasoning_effort = v.lower()
            return True, f"reasoning_effort set to {self.reasoning_effort} (effective temp: {self.effective_temperature})"

        elif k in ("yolo", "auto_approve"):
            truthy = v.lower() in ("1", "true", "yes", "on", "enable")
            self.yolo = truthy
            self.mode = "build" if truthy else "plan"
            return True, f"yolo mode set to {self.yolo} (mode: {self.mode.upper()})"

        elif k in ("temp", "temperature"):
            try:
                t = float(v)
                if not (0.0 <= t <= 2.0):
                    return False, "Temperature must be between 0.0 and 2.0"
                self.temperature = t
                return True, f"temperature set to {self.temperature}"
            except ValueError:
                return False, f"Invalid float value for temperature: '{v}'"

        elif k in ("steps", "max_steps"):
            try:
                s = int(v)
                if s < 1:
                    return False, "max_steps must be at least 1"
                self.max_steps = s
                return True, f"max_steps set to {self.max_steps}"
            except ValueError:
                return False, f"Invalid integer value for max_steps: '{v}'"

        elif k in ("timeout",):
            try:
                to = float(v)
                if to <= 0:
                    return False, "timeout must be positive"
                self.timeout = to
                return True, f"timeout set to {self.timeout}s"
            except ValueError:
                return False, f"Invalid float value for timeout: '{v}'"

        elif k in ("cwd", "dir"):
            expanded = os.path.abspath(os.path.expanduser(v))
            if not os.path.isdir(expanded):
                return False, f"Directory does not exist: {expanded}"
            self.cwd = expanded
            return True, f"cwd set to {self.cwd}"

        else:
            valid_keys = [
                "mode", "server", "model", "effort", "yolo", "temperature",
                "max_steps", "timeout", "cwd"
            ]
            return False, f"Unknown config key '{key}'. Available: {', '.join(valid_keys)}"
