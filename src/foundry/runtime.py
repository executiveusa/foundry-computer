import base64
import subprocess
from abc import ABC, abstractmethod

from .config import settings

PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
MAX_OUTPUT = 1_000_000


class Runtime(ABC):
    @abstractmethod
    def create(self, computer: dict): ...
    @abstractmethod
    def lifecycle(self, computer: dict, action: str): ...
    @abstractmethod
    def action(self, computer: dict, action: str, payload: dict): ...
    def screenshot(self, computer: dict) -> bytes:
        return PNG_1X1


def _cap(text: str) -> tuple[str, bool]:
    if len(text) > MAX_OUTPUT:
        return text[:MAX_OUTPUT], True
    return text, False


class MockRuntime(Runtime):
    """Contract-test runtime. bash executes on the control-plane host and is
    refused unless FOUNDRY_MOCK_ALLOW_BASH is explicitly set (tests only)."""

    def create(self, computer):
        return {"runtime_id": "mock-" + computer["id"]}

    def lifecycle(self, computer, action):
        return {"ok": True, "action": action}

    def action(self, computer, action, payload):
        if action == "bash":
            if not settings.mock_allow_bash:
                return {
                    "error": "mock bash disabled (set FOUNDRY_MOCK_ALLOW_BASH=1 in tests only)",
                    "exit_code": 126,
                    "stdout": "",
                    "stderr": "",
                }
            try:
                p = subprocess.run(
                    ["bash", "-lc", payload["command"]],
                                   check=False,
                    capture_output=True,
                    text=True,
                    timeout=payload.get("timeout_seconds", 60),
                )
            except subprocess.TimeoutExpired as e:
                out = (e.stdout or "") if isinstance(e.stdout, str) else ""
                out, truncated = _cap(out)
                return {
                    "error": "timeout",
                    "exit_code": 124,
                    "stdout": out,
                    "stderr": "",
                    "truncated": truncated,
                }
            stdout, t1 = _cap(p.stdout)
            stderr, t2 = _cap(p.stderr)
            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": p.returncode,
                "truncated": t1 or t2,
            }
        return {"ok": True, "action": action}
