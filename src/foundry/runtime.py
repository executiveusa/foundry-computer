import base64
import contextlib
import hashlib
import os
import re
import resource
import selectors
import signal
import subprocess
import tempfile
import time
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
        raise UnsupportedAction("screenshot")


class UnsupportedAction(Exception):
    """The backend has no real backing for this action (consistent 501)."""

    def __init__(self, action: str):
        self.action = action
        super().__init__(f"unsupported_action: {action}")


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
        # honest contract: mock backs bash only; everything else is 501
        return {"error": "unsupported_action", "action": action, "backend": "mock"}


_SAFE_ENV = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8"}


def _limit(timeout: int):
    """preexec: rlimits only (uid/gid/session use Popen's thread-safe kwargs)."""

    def inner():
        resource.setrlimit(resource.RLIMIT_CPU, (timeout + 5, timeout + 5))
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024**2, 100 * 1024**2))
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))

    return inner


_SAFE_ENV_BASE = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8"}


def _limit(timeout: int):
    """preexec: rlimits only (uid/gid/session use Popen's thread-safe kwargs)."""

    def inner():
        resource.setrlimit(resource.RLIMIT_CPU, (timeout + 5, timeout + 5))
        resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
        resource.setrlimit(resource.RLIMIT_FSIZE, (100 * 1024**2, 100 * 1024**2))
        resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))

    return inner


def _worker_uid(computer_id: str) -> int:
    return 10000 + int(hashlib.sha256(computer_id.encode()).hexdigest(), 16) % 50000


class BashRuntime(Runtime):
    """DEV/TEST executor, opt-in via FOUNDRY_RUNTIME_BACKEND=bash.

    NOT A SECURITY BOUNDARY. Runs bash on this host in the same container as
    the control plane. Demotion is best-effort: per-computer uid, scrubbed
    env, rlimits, process-group timeout kill, incremental output cap. Known
    holes: a setsid/nohup escape survives the group kill, rlimits are per-uid
    rather than aggregate, and there is no network restriction. Untrusted
    commands belong in slice 2 (per-computer rootless containers driven by a
    separate host daemon). Dev and tests only.
    """

    def __init__(self):
        if os.geteuid() != 0:
            raise RuntimeError(
                "BashRuntime must start as root so it can demote workers to "
                "unprivileged per-computer uids; refusing to run un-denoted."
            )

    def create(self, computer):
        return {"runtime_id": "bash-" + computer["id"]}

    def lifecycle(self, computer, action):
        return {"ok": True, "action": action}

    def _workdir(self, computer, uid):
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", computer["id"])[:64]
        d = os.path.join(tempfile.gettempdir(), f"foundry-bash-{safe}")
        os.makedirs(d, exist_ok=True)
        os.chown(d, uid, uid)
        os.chmod(d, 0o700)
        return d

    def _kill_group(self, proc):
        with contextlib.suppress(OSError):  # group already gone
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

    def _drain(self, sel, bufs, deadline):
        truncated = False
        while sel.get_map() and time.monotonic() < deadline:
            for key, _ in sel.select(timeout=0.1):
                chunk = key.fileobj.read1(65536)
                if not chunk:
                    sel.unregister(key.fileobj)
                    continue
                buf = bufs[key.data]
                room = MAX_OUTPUT - len(buf)
                if room > 0:
                    buf += chunk[:room]
                if len(buf) >= MAX_OUTPUT:
                    truncated = True
        return truncated

    def _pump(self, proc, timeout):
        """Incrementally drain stdout/stderr capped at MAX_OUTPUT each.
        Kills the process group on timeout or cap overflow, then reaps with a
        bounded wait. Returns (stdout, stderr, status, truncated)."""
        sel = selectors.DefaultSelector()
        sel.register(proc.stdout, selectors.EVENT_READ, "out")
        sel.register(proc.stderr, selectors.EVENT_READ, "err")
        bufs = {"out": bytearray(), "err": bytearray()}
        status = "ok"
        truncated = self._drain(sel, bufs, time.monotonic() + timeout)
        if sel.get_map():
            status = "timeout" if proc.poll() is None and not truncated else "cap"
            self._kill_group(proc)
            truncated = self._drain(sel, bufs, time.monotonic() + 1.0) or True
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(OSError):
                proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(timeout=5)
        out = bytes(bufs["out"]).decode("utf-8", "replace")
        err = bytes(bufs["err"]).decode("utf-8", "replace")
        return out, err, status, truncated

    def action(self, computer, action, payload):
        if action != "bash":
            # bash backend backs shell only; desktop/fs need slice 2
            return {"error": "unsupported_action", "action": action, "backend": "bash"}
        uid = _worker_uid(computer["id"])
        cwd = self._workdir(computer, uid)
        timeout = min(int(payload.get("timeout_seconds", 60)), 300)
        env = dict(_SAFE_ENV_BASE, HOME=cwd)
        proc = subprocess.Popen(
            ["bash", "-c", payload["command"]],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,
            user=uid,
            group=uid,
            extra_groups=[],
            preexec_fn=_limit(timeout),  # noqa: PLW1509 - rlimits only; demotion via thread-safe kwargs
        )
        out, err, status, truncated = self._pump(proc, timeout)
        if status == "timeout":
            return {
                "error": "timeout",
                "exit_code": 124,
                "stdout": out,
                "stderr": "",
                "truncated": truncated,
            }
        return {
            "stdout": out,
            "stderr": err,
            "exit_code": proc.returncode,
            "truncated": truncated,
        }
