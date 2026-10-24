"""Weekly-client-brief job tests: draft-only policy, sources required, caps."""

from foundry.firstmate import Caps, FirstMate, PolicyError, TaskState
from foundry.jobs.weekly_client_brief import make_task, run


class FakeStore:
    def __init__(self):
        self.events = []
        self.objects = {}

    def event(self, kind, object_id, payload):
        self.events.append((kind, object_id, payload))

    def put(self, kind, id, data):
        self.objects[(kind, id)] = data


class StubModel:
    model = "test-model"

    def __init__(self, text="# Weekly brief\n\nSales rose [1].", usage=None):
        self.text = text
        self.last_usage = usage or {"total_tokens": 500, "cost_usd": 0.01}

    def complete(self, messages):
        return self.text


def researcher(client, topics):
    return [
        {"title": "Q3 numbers", "note": "sales rose 10%", "url": "https://example.com/q3"},
        {"title": "Launch", "note": "new SKU launched", "url": "https://example.com/launch"},
    ]


def setup(caps=None):
    store = FakeStore()
    mate = FirstMate(store=store)
    task = mate.submit(make_task("acme", ["market"], caps=caps))
    return mate, store, task


def test_happy_path_draft_only_with_sources_and_receipt():
    mate, store, task = setup()
    receipt = run(task, mate, StubModel(), researcher)
    assert mate.states[task.id] == TaskState.done
    assert receipt.draft_only is True
    assert receipt.sources == ["https://example.com/q3", "https://example.com/launch"]
    assert receipt.tokens == 500
    assert receipt.notes == "draft stored; nothing sent"
    artifact = store.objects[("artifact", f"brief-{task.id}")]
    assert artifact["kind"] == "markdown_draft"


def test_policy_never_allows_send():
    mate, _, task = setup()
    import pytest

    with pytest.raises(PolicyError):
        mate.authorize(task.id, "send")


def test_no_sources_fails_honestly():
    mate, _, task = setup()
    receipt = run(task, mate, StubModel(), lambda c, t: [])
    assert mate.states[task.id] == TaskState.failed
    assert "no citable sources" in receipt.notes


def test_token_cap_fails_run_and_marks_receipt():
    mate, _, task = setup(caps=Caps(max_tokens=100))
    receipt = run(task, mate, StubModel(usage={"total_tokens": 5000, "cost_usd": 0.0}), researcher)
    assert mate.states[task.id] == TaskState.failed
    assert receipt.over_caps is True
