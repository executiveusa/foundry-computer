"""First-mate protocol tests: policy gateway, caps, approvals, dedupe, receipts."""

import pytest

from foundry.firstmate import (
    ApprovalKind,
    CapExceeded,
    Caps,
    FirstMate,
    PolicyError,
    Receipt,
    TaskState,
)


class FakeStore:
    def __init__(self):
        self.events = []

    def event(self, kind, object_id, payload):
        self.events.append((kind, object_id, payload))


def make_mate(**caps):
    store = FakeStore()
    mate = FirstMate(store=store)
    spec = mate.submit(_spec(caps))
    mate.start(spec.id)
    return mate, store, spec


def _spec(caps):
    from foundry.firstmate import TaskSpec

    return TaskSpec(job="weekly-client-brief", inputs={"client": "acme"}, caps=Caps(**caps))


def test_forbidden_verb_is_refused_and_audited():
    mate, store, spec = make_mate()
    with pytest.raises(PolicyError):
        mate.authorize(spec.id, "send")
    assert any(p.get("verb") == "send" and p.get("event") == "denied" for _, _, p in store.events)


def test_allowed_verb_passes():
    mate, _, spec = make_mate()
    mate.authorize(spec.id, "research")


def test_token_cap_stops_the_task():
    mate, _, spec = make_mate(max_tokens=100)
    with pytest.raises(CapExceeded):
        mate.record_usage(spec.id, tokens=101)


def test_cost_cap_stops_the_task():
    mate, _, spec = make_mate(max_cost_usd=0.5)
    with pytest.raises(CapExceeded):
        mate.record_usage(spec.id, cost_usd=0.51)


def test_approval_roundtrip():
    mate, _, spec = make_mate()
    req = mate.request_approval(spec.id, ApprovalKind.publish, "publish draft?", preview="# brief")
    assert mate.states[spec.id] == TaskState.awaiting_approval
    assert mate.resolve_approval(spec.id, req.id, "approve") is True
    assert mate.states[spec.id] == TaskState.running
    with pytest.raises(PolicyError):
        mate.resolve_approval(spec.id, req.id, "approve")  # double resolve refused


def test_reject_returns_false():
    mate, _, spec = make_mate()
    req = mate.request_approval(spec.id, ApprovalKind.send, "send email?")
    assert mate.resolve_approval(spec.id, req.id, "reject") is False


def test_follow_up_dedupes():
    mate, _, spec = make_mate()
    assert mate.follow_up(spec.id, "check pricing", "pricing") is not None
    assert mate.follow_up(spec.id, "check pricing again", "pricing") is None


def test_finish_writes_receipt_to_audit():
    mate, store, spec = make_mate()
    receipt = Receipt(task_id=spec.id, job=spec.job, started_at="t0", sources=["https://x.test"])
    mate.finish(spec.id, receipt)
    assert mate.states[spec.id] == TaskState.done
    kinds = [k for k, _, _ in store.events]
    assert "firstmate.receipt" in kinds
