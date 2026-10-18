"""BashRuntime: DEV/TEST executor only (NOT a security boundary)."""

import os
import stat
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from foundry.runtime import BashRuntime, MockRuntime, _worker_uid
from foundry.store import Store

C = {"id": "t1"}
C2 = {"id": "t2"}


def test_bash_executes_for_real():
    r = BashRuntime().action(C, "bash", {"command": "echo hi"})
    assert r["exit_code"] == 0
    assert r["stdout"].strip() == "hi"


def test_bash_env_is_scrubbed(monkeypatch):
    monkeypatch.setenv("FOUNDRY_API_KEY", "supersecret-value")
    monkeypatch.setenv("HOME", "/root")
    r = BashRuntime().action(C, "bash", {"command": "echo k=$FOUNDRY_API_KEY h=$HOME"})
    assert "supersecret-value" not in r["stdout"]
    assert "foundry-bash-t1" in r["stdout"]


def test_bash_timeout_kills_fast():
    t0 = time.time()
    r = BashRuntime().action(C, "bash", {"command": "sleep 30", "timeout_seconds": 1})
    assert r["error"] == "timeout"
    assert r["exit_code"] == 124
    assert time.time() - t0 < 5


def test_bash_timeout_keeps_partial_output():
    r = BashRuntime().action(C, "bash", {"command": "echo part1; sleep 30", "timeout_seconds": 1})
    assert r["error"] == "timeout"
    assert "part1" in r["stdout"]


def test_bash_timeout_kills_grandchildren():
    r = BashRuntime().action(C, "bash", {"command": "sleep 30 & wait", "timeout_seconds": 1})
    assert r["error"] == "timeout"
    chk = BashRuntime().action(C, "bash", {"command": "pgrep -f '[s]leep 30' || true"})
    assert chk["stdout"].strip() == ""


def test_bash_runs_as_per_computer_unprivileged_uid():
    if os.geteuid() != 0:
        pytest.skip("host not root")
    r1 = BashRuntime().action(C, "bash", {"command": "id -u"})
    r2 = BashRuntime().action(C2, "bash", {"command": "id -u"})
    assert r1["stdout"].strip() == str(_worker_uid("t1"))
    assert r2["stdout"].strip() == str(_worker_uid("t2"))
    assert r1["stdout"] != r2["stdout"]


def test_bash_worker_has_no_supplementary_groups():
    if os.geteuid() != 0:
        pytest.skip("host not root")
    r = BashRuntime().action(C, "bash", {"command": "id -G"})
    groups = r["stdout"].split()
    assert "0" not in groups
    assert len(groups) == 1


def test_bash_refuses_to_start_unless_root(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    with pytest.raises(RuntimeError, match="demote"):
        BashRuntime()


def test_bash_output_cap_is_incremental_and_fast():
    t0 = time.time()
    r = BashRuntime().action(C, "bash", {"command": "head -c 5000000 /dev/zero | tr '\\0' x"})
    assert r["truncated"] is True
    assert len(r["stdout"]) == 1_000_000
    assert time.time() - t0 < 15  # killed at cap, not after buffering 5MB slowly


def test_bash_concurrent_actions_isolated():
    with ThreadPoolExecutor(max_workers=4) as ex:
        rs = list(
            ex.map(
                lambda i: BashRuntime().action(
                    {"id": f"conc{i}"}, "bash", {"command": f"echo w{i}; id -u"}
                ),
                range(4),
            )
        )
    for i, r in enumerate(rs):
        assert f"w{i}" in r["stdout"]
    uids = {r["stdout"].strip().splitlines()[-1] for r in rs}
    assert len(uids) == 4  # one uid per computer


def test_store_database_file_is_owner_only(tmp_path):
    db = str(tmp_path / "t.db")
    Store(db)
    mode = stat.S_IMODE(os.stat(db).st_mode)
    assert mode == 0o600


def test_default_backend_stays_mock():
    import foundry.main as m

    assert isinstance(m.runtime, MockRuntime)


def test_non_bash_actions_passthrough():
    r = BashRuntime().action(C, "screenshot", {})
    assert r["ok"] is True
