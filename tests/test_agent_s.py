"""Agent-S adapter loop: stubs only, no network, no model spend."""

import pytest

from foundry.agent_s import AgentSAdapter, OpenAICompatibleModel

C = {"id": "a1", "name": "agentbox"}


class StubModel:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        return self.replies.pop(0) if self.replies else '{"done": true, "summary": "end"}'


class ScriptedRuntime:
    def __init__(self, supported=()):
        self.supported = set(supported)
        self.calls = []

    def screenshot(self, computer):
        raise RuntimeError("no desktop")

    def action(self, computer, action, payload):
        self.calls.append((action, payload))
        if action in self.supported:
            return {"ok": True, "action": action}
        return {"error": "unsupported_action", "action": action}


def test_done_flow_executes_permitted_supported_actions():
    rt = ScriptedRuntime(supported={"open_url"})
    m = StubModel(
        [
            '{"action": "open_url", "payload": {"url": "https://example.com"}}',
            '{"done": true, "summary": "opened"}',
        ]
    )
    a = AgentSAdapter(rt, m, permission=lambda c, act, p: True)
    r = a.run(C, "open example.com")
    assert r["status"] == "done"
    assert r["summary"] == "opened"
    assert rt.calls == [("open_url", {"url": "https://example.com"})]
    assert len(r["history"]) == 1


def test_default_permission_is_deny_all():
    rt = ScriptedRuntime(supported={"bash"})
    m = StubModel(['{"action": "bash", "payload": {"command": "echo hi"}}'])
    a = AgentSAdapter(rt, m)  # no permission hook
    r = a.run(C, "say hi")
    assert r["status"] == "blocked"
    assert rt.calls == []  # nothing executed


def test_permission_denied_blocks_and_records():
    rt = ScriptedRuntime(supported={"bash"})
    m = StubModel(['{"action": "bash", "payload": {"command": "rm -rf /"}}'])
    a = AgentSAdapter(rt, m, permission=lambda c, act, p: False)
    r = a.run(C, "nuke")
    assert r["status"] == "blocked"
    assert r["history"][0]["blocked"] == "permission_denied"
    assert rt.calls == []


def test_unsupported_runtime_action_escalates():
    rt = ScriptedRuntime(supported=set())  # no desktop
    m = StubModel(['{"action": "click", "payload": {"x": 1, "y": 2}}'])
    a = AgentSAdapter(rt, m, permission=lambda c, act, p: True)
    r = a.run(C, "click the button")
    assert r["status"] == "escalated"
    assert "needs a real runtime" in r["reason"]


def test_unknown_action_escalates():
    rt = ScriptedRuntime()
    m = StubModel(['{"action": "teleport", "payload": {}}'])
    a = AgentSAdapter(rt, m, permission=lambda c, act, p: True)
    assert a.run(C, "beam up")["status"] == "escalated"


def test_unparseable_reply_recovers_then_finishes():
    rt = ScriptedRuntime(supported={"wait"})
    m = StubModel(["not json at all", '{"action": "wait", "payload": {"seconds": 1}}'])
    a = AgentSAdapter(rt, m, permission=lambda c, act, p: True)
    r = a.run(C, "wait a bit")
    assert r["status"] == "done"
    assert r["history"][0]["error"] == "unparseable_model_reply"


def test_max_steps_caps_runaway_loops():
    rt = ScriptedRuntime(supported={"wait"})
    m = StubModel(['{"action": "wait", "payload": {"seconds": 1}}'] * 50)
    a = AgentSAdapter(rt, m, permission=lambda c, act, p: True, max_steps=5)
    r = a.run(C, "loop forever")
    assert r["status"] == "max_steps"
    assert len(rt.calls) == 5


def test_model_requires_explicit_config(monkeypatch):
    for k in ("FOUNDRY_AGENT_MODEL_BASE_URL", "FOUNDRY_AGENT_MODEL_API_KEY", "FOUNDRY_AGENT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        OpenAICompatibleModel()


def test_observe_reports_no_desktop_honestly():
    a = AgentSAdapter(ScriptedRuntime(), StubModel([]))
    assert a._observe(C) == {"screenshot_available": False, "computer": "agentbox"}
