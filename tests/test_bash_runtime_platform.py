"""BashRuntime platform guards: run on any user (no root required)."""

import os
import stat

import pytest

from foundry.runtime import BashRuntime, MockRuntime
from foundry.store import Store


def test_bash_refuses_to_start_unless_root(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: 1000)
    with pytest.raises(RuntimeError, match="demote"):
        BashRuntime()


def test_store_database_file_is_owner_only(tmp_path):
    db = str(tmp_path / "t.db")
    Store(db)
    mode = stat.S_IMODE(os.stat(db).st_mode)
    assert mode == 0o600


def test_default_backend_stays_mock():
    import foundry.main as m

    assert isinstance(m.runtime, MockRuntime)
