"""BashRuntime: real local execution, intended only inside an isolated pod."""

import time

from foundry.runtime import BashRuntime, MockRuntime

C = {"id": "t1"}


def test_bash_executes_for_real():
    r = BashRuntime().action(C, "bash", {"command": "echo hi"})
    assert r["exit_code"] == 0
    assert r["stdout"].strip() == "hi"


def test_bash_env_is_scrubbed(monkeypatch):
    monkeypatch.setenv("FOUNDRY_API_KEY", "supersecret-value")
    monkeypatch.setenv("HOME", "/root")
    r = BashRuntime().action(C, "bash", {"command": "echo k=$FOUNDRY_API_KEY h=$HOME"})
    assert "supersecret-value" not in r["stdout"]
    assert "h=/tmp" in r["stdout"]


def test_bash_timeout_kills_fast():
    t0 = time.time()
    r = BashRuntime().action(C, "bash", {"command": "sleep 30", "timeout_seconds": 1})
    assert r["error"] == "timeout"
    assert r["exit_code"] == 124
    assert time.time() - t0 < 5


def test_bash_timeout_kills_grandchildren():
    r = BashRuntime().action(
        C,
        "bash",
        {
            "command": "sleep 30 & wait",
            "timeout_seconds": 1,
        },
    )
    assert r["error"] == "timeout"
    chk = BashRuntime().action(C, "bash", {"command": "pgrep -f '[s]leep 30' || true"})
    assert chk["stdout"].strip() == ""


def test_bash_runs_unprivileged_when_root():
    import os

    if os.geteuid() != 0:
        import pytest

        pytest.skip("host not root")
    r = BashRuntime().action(C, "bash", {"command": "id -u"})
    assert r["stdout"].strip() == "65534"


def test_bash_output_cap():
    r = BashRuntime().action(C, "bash", {"command": "head -c 2000000 /dev/zero | tr '\\0' x"})
    assert r["truncated"] is True
    assert len(r["stdout"]) == 1_000_000


def test_default_backend_stays_mock():
    import foundry.main as m

    assert isinstance(m.runtime, MockRuntime)


def test_non_bash_actions_passthrough():
    r = BashRuntime().action(C, "screenshot", {})
    assert r["ok"] is True
