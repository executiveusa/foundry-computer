import base64
import contextlib
import os
import resource
import signal
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
            if not (settings.dev_mode and settings.mock_allow_bash):
                return {
                    "error": "mock_bash_disabled",
                    "exit_code": None,
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


_SAFE_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8"}


def _limit(timeout: int):
    """preexec: rlimits only (uid/gid/session use Popen's thread-safe kwargs)."""

    def inner():
        resource.setrlimit(resource.RLIMIT_CPU, (timeout + 5, timeout + 5))
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024**2, 100 * 1024**2))
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))

    return inner


class BashRuntime(Runtime):
    """Real executor: runs bash on the local machine. Intended ONLY inside a
    disposable, credential-free isolation boundary (pod/VM). Selected via
    FOUNDRY_RUNTIME_BACKEND=bash; the default backend stays MockRuntime."""

    def create(self, computer):
        return {"runtime_id": "bash-" + computer["id"]}

    def lifecycle(self, computer, action):
        return {"ok": True, "action": action}

    def action(self, computer, action, payload):
        if action != "bash":
            return {"ok": True, "action": action}
        timeout = min(int(payload.get("timeout_seconds", 60)), 300)
        popen_kw: dict = {"start_new_session": True}
        if os.geteuid() == 0:
            popen_kw.update({"user": 65534, "group": 65534})  # nobody:nogroup
        proc = subprocess.Popen(
            ["bash", "-c", payload["command"]],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd="/tmp",
            env=dict(_SAFE_ENV),
            preexec_fn=_limit(timeout),  # noqa: PLW1509 - rlimits only; uid/gid/session via kwargs
            **popen_kw,
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):  # process group already gone
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            out, _ = proc.communicate()
            out, truncated = _cap(out or "")
            return {
                "error": "timeout",
                "exit_code": 124,
                "stdout": out,
                "stderr": "",
                "truncated": truncated,
            }
        stdout, t1 = _cap(out)
        stderr, t2 = _cap(err)
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": proc.returncode,
            "truncated": t1 or t2,
        }
