"""Contract tests for the OpenSandbox runtime. The SDK is faked: no network,
no Docker, no spend."""

from typing import ClassVar

import pytest

from foundry.config import Settings
from foundry.opensandbox_runtime import OpenSandboxRuntime
from foundry.runtime import UnsupportedAction


class _Msg:
    def __init__(self, text):
        self.text = text


class _Logs:
    stdout: ClassVar = [_Msg("hello from sandbox\n")]
    stderr: ClassVar = []


class _Execution:
    exit_code = 0
    error = None
    logs = _Logs()


class _Commands:
    def __init__(self):
        self.ran = []

    def run(self, command, timeout=None):
        self.ran.append(command)
        return _Execution()


class FakeSandbox:
    def __init__(self, sandbox_id="sbx-1"):
        self.id = sandbox_id
        self.commands = _Commands()
        self.paused = False
        self.resumed = False
        self.killed = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.resumed = True

    def kill(self):
        self.killed = True


def make_runtime():
    calls = []

    def factory(**kwargs):
        calls.append(kwargs)
        return FakeSandbox()

    return OpenSandboxRuntime(
        factory=factory, allowlist=["api.openai.com"], default_image="img:test", timeout_minutes=30
    ), calls


def computer(**kw):
    base = {"id": "c1", "workspace_id": "w1", "cpu": 2, "ram": 8, "template_ref": None}
    base.update(kw)
    return base


def test_create_maps_computer_to_sandbox_with_deny_all_egress():
    rt, calls = make_runtime()
    out = rt.create(computer())
    assert out["runtime_id"] == "osb-sbx-1"
    assert out["backend"] == "opensandbox"
    call = calls[0]
    assert call["image"] == "img:test"
    assert call["metadata"]["foundry_computer_id"] == "c1"
    assert call["resource"] == {"cpu": "2", "memory": "8Gi"}
    # default-deny posture: only allowlisted targets are passed for allow rules
    assert call["network_policy"] == ["api.openai.com"]
    assert call["timeout_minutes"] == 30


def test_template_ref_overrides_default_image():
    rt, calls = make_runtime()
    rt.create(computer(template_ref="opensandbox/desktop:latest"))
    assert calls[0]["image"] == "opensandbox/desktop:latest"


def test_bash_runs_in_sandbox_and_normalizes():
    rt, _ = make_runtime()
    out = rt.create(computer())
    c = computer(runtime_id=out["runtime_id"])
    result = rt.action(c, "bash", {"command": "echo hi"})
    assert result["stdout"] == "hello from sandbox\n"
    assert result["exit_code"] == 0
    assert rt._sandboxes["osb-sbx-1"].commands.ran == ["echo hi"]


def test_unsupported_actions_raise_consistently():
    rt, _ = make_runtime()
    out = rt.create(computer())
    c = computer(runtime_id=out["runtime_id"])
    for action in ("click", "type", "key", "scroll", "upload", "download"):
        with pytest.raises(UnsupportedAction):
            rt.action(c, action, {})
    with pytest.raises(UnsupportedAction):
        rt.screenshot(c)


def test_lifecycle_maps_to_handle():
    rt, _ = make_runtime()
    out = rt.create(computer())
    c = computer(runtime_id=out["runtime_id"])
    handle = rt._sandboxes["osb-sbx-1"]
    rt.lifecycle(c, "stop")
    assert handle.paused
    rt.lifecycle(c, "start")
    assert handle.resumed
    rt.lifecycle(c, "delete")
    assert handle.killed
    with pytest.raises(UnsupportedAction):
        rt.lifecycle(c, "snapshot")


def test_unknown_sandbox_is_an_honest_error():
    rt, _ = make_runtime()
    with pytest.raises(UnsupportedAction):
        rt.action(computer(runtime_id="osb-gone"), "bash", {"command": "ls"})


def test_config_fails_closed_without_domain():
    with pytest.raises(ValueError, match="OPENSANDBOX_DOMAIN"):
        Settings(runtime_backend="opensandbox")


def test_config_allows_keyless_only_in_dev_mode():
    # conftest sets FOUNDRY_DEV_MODE=true
    s = Settings(runtime_backend="opensandbox", opensandbox_domain="127.0.0.1:8080")
    assert s.runtime_backend == "opensandbox"
