import importlib
import os
import tempfile

os.environ.setdefault("FOUNDRY_DEV_MODE", "true")
os.environ.setdefault("FOUNDRY_DATABASE_PATH", tempfile.mktemp())
import pytest


def _fresh_config(monkeypatch, **env):
    for k in list(os.environ):
        if k.startswith("FOUNDRY_"):
            monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import foundry.config as cfg

    importlib.reload(cfg)
    return cfg


def test_default_key_refused_outside_dev(monkeypatch):
    for k in list(os.environ):
        if k.startswith("FOUNDRY_"):
            monkeypatch.delenv(k, raising=False)
    from foundry.config import Settings

    with pytest.raises(ValueError):
        Settings(_env_file=None)  # default key, no dev mode -> must fail closed


def test_short_key_refused_outside_dev(monkeypatch):
    for k in list(os.environ):
        if k.startswith("FOUNDRY_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FOUNDRY_API_KEY", "short")
    from foundry.config import Settings

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_default_key_allowed_in_explicit_dev_mode(monkeypatch):
    for k in list(os.environ):
        if k.startswith("FOUNDRY_"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FOUNDRY_DEV_MODE", "true")
    from foundry.config import Settings

    s = Settings(_env_file=None)
    assert s.api_key == "foundry-local-dev"


def _client(monkeypatch, **env):
    _fresh_config(monkeypatch, **env)  # reload side effect
    import foundry.main as m
    import foundry.runtime as rt

    importlib.reload(rt)
    importlib.reload(m)
    from fastapi.testclient import TestClient

    return TestClient(m.app)


BASE = {
    "FOUNDRY_DATABASE_PATH": tempfile.mktemp(),
    "FOUNDRY_DEV_MODE": "true",
    "FOUNDRY_PREVIEW_USER": "client",
    "FOUNDRY_PREVIEW_PASSWORD": "test-preview-only",
}
H = {"Authorization": "Bearer foundry-local-dev"}


def _computer(c):
    w = c.post("/api/workspaces", headers=H, json={"name": "sec"})
    assert w.status_code == 201
    comp = c.post("/api/computers", headers=H, json={"workspace_id": w.json()["id"], "name": "c1"})
    assert comp.status_code == 201
    return comp.json()["id"]


def test_mock_bash_refused_when_not_opted_in(monkeypatch):
    c = _client(monkeypatch, **BASE)
    cid = _computer(c)
    r = c.post(f"/api/computers/{cid}/bash", headers=H, json={"command": "echo hi"})
    assert r.status_code == 403


def test_mock_bash_allowed_with_explicit_optin(monkeypatch):
    c = _client(monkeypatch, **{**BASE, "FOUNDRY_MOCK_ALLOW_BASH": "1"})
    cid = _computer(c)
    r = c.post(f"/api/computers/{cid}/bash", headers=H, json={"command": "printf ok"})
    assert r.status_code == 200 and r.json()["stdout"] == "ok"


def test_bash_timeout_returns_structured_error(monkeypatch):
    c = _client(monkeypatch, **{**BASE, "FOUNDRY_MOCK_ALLOW_BASH": "1"})
    cid = _computer(c)
    r = c.post(
        f"/api/computers/{cid}/bash", headers=H, json={"command": "sleep 5", "timeout_seconds": 1}
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("error") == "timeout" and body.get("exit_code") == 124


def test_bash_output_capped(monkeypatch):
    c = _client(monkeypatch, **{**BASE, "FOUNDRY_MOCK_ALLOW_BASH": "1"})
    cid = _computer(c)
    r = c.post(
        f"/api/computers/{cid}/bash",
        headers=H,
        json={"command": "head -c 3000000 /dev/zero | tr '\\0' 'A'"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("truncated") is True and len(body["stdout"]) <= 1_000_000
