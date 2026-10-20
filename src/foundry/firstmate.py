"""First-mate bridge: a typed protocol so one supervising agent (the "first
mate") can run many sandboxed workers, on any models, with per-task
follow-ups, approvals, progress and end-of-task receipts.

Honest scope: this is a PROTOCOL plus a reference implementation inside the
Foundry control plane. It is not a bundled Instinct and does not provision
Instinct for clients - no such capability exists or is claimed. The typed
per-task follow-up / approval / progress patterns are borrowed from
MIT-licensed hermes-voice-ios; gateway-before-action and audit-first align
with OpenBot's design (studied, not depended on). Every state change lands in
the Foundry audit log when a Store is attached.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(UTC).isoformat()


class TaskState(str, Enum):
    queued = "queued"
    running = "running"
    awaiting_approval = "awaiting_approval"
    blocked = "blocked"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class ApprovalKind(str, Enum):
    spend = "spend"
    send = "send"
    publish = "publish"
    credential_use = "credential_use"
    destructive = "destructive"
    other = "other"


class PolicyError(Exception):
    """The worker attempted a verb its task policy forbids."""


class CapExceeded(Exception):
    """A usage cap (actions, tokens, cost) was crossed; the task must stop."""


class Caps(BaseModel):
    max_actions: int = 200
    max_tokens: int = 200_000
    max_cost_usd: float = 5.0
    max_minutes: int = 60


class TaskSpec(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    job: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    allowed_verbs: set[str] = Field(default_factory=lambda: {"research", "read", "write_draft"})
    caps: Caps = Field(default_factory=Caps)
    created_at: str = Field(default_factory=_now)


class ProgressEvent(BaseModel):
    task_id: str
    at: str = Field(default_factory=_now)
    state: TaskState
    note: str
    pct: int | None = None


class ApprovalRequest(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    task_id: str
    kind: ApprovalKind
    summary: str
    preview: str = ""
    options: list[str] = Field(default_factory=lambda: ["approve", "reject"])
    created_at: str = Field(default_factory=_now)
    resolved: bool = False
    decision: str | None = None


class FollowUp(BaseModel):
    task_id: str
    body: str
    dedupe_key: str
    at: str = Field(default_factory=_now)


class Receipt(BaseModel):
    """The end-of-shift report: what ran, what it used, what it made."""

    task_id: str
    job: str
    started_at: str
    finished_at: str = Field(default_factory=_now)
    actions: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    models: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    caps: Caps = Field(default_factory=Caps)
    over_caps: bool = False
    draft_only: bool = True
    notes: str = ""


class _Usage(BaseModel):
    actions: int = 0
    tokens: int = 0
    cost_usd: float = 0.0


class FirstMate:
    """Reference implementation of the first-mate surface.

    A supervising agent (human, Instinct-style agent, or cron) drives workers
    through these calls; workers call authorize/record_usage before acting.
    """

    def __init__(self, store=None):
        self.store = store
        self.tasks: dict[str, TaskSpec] = {}
        self.states: dict[str, TaskState] = {}
        self.approvals: dict[str, ApprovalRequest] = {}
        self._usage: dict[str, _Usage] = {}
        self._follow_up_keys: set[str] = set()
        self._started: dict[str, str] = {}

    def _audit(self, kind: str, object_id: str, payload: dict):
        if self.store is not None:
            self.store.event(kind, object_id, payload)

    # -- task lifecycle ---------------------------------------------------

    def submit(self, spec: TaskSpec) -> TaskSpec:
        self.tasks[spec.id] = spec
        self.states[spec.id] = TaskState.queued
        self._usage[spec.id] = _Usage()
        self._audit("firstmate.task", spec.id, {"event": "submitted", "job": spec.job})
        return spec

    def start(self, task_id: str):
        self.states[task_id] = TaskState.running
        self._started[task_id] = _now()
        self._audit("firstmate.task", task_id, {"event": "started"})

    def usage(self, task_id: str) -> _Usage:
        return self._usage[task_id]

    # -- policy + caps (gateway before action) ------------------------------

    def authorize(self, task_id: str, verb: str):
        spec = self.tasks[task_id]
        if verb not in spec.allowed_verbs:
            self._audit("firstmate.policy", task_id, {"event": "denied", "verb": verb})
            raise PolicyError(f"verb '{verb}' is not allowed for task {task_id}")
        self._audit("firstmate.policy", task_id, {"event": "allowed", "verb": verb})

    def record_usage(
        self, task_id: str, *, actions: int = 0, tokens: int = 0, cost_usd: float = 0.0
    ):
        u = self._usage[task_id]
        u.actions += actions
        u.tokens += tokens
        u.cost_usd += cost_usd
        caps = self.tasks[task_id].caps
        if u.actions > caps.max_actions or u.tokens > caps.max_tokens or u.cost_usd > caps.max_cost_usd:
            self._audit("firstmate.caps", task_id, {"event": "exceeded", "usage": u.model_dump()})
            raise CapExceeded(f"task {task_id} crossed its usage cap: {u.model_dump()}")

    # -- supervision surface ------------------------------------------------

    def progress(self, task_id: str, note: str, pct: int | None = None) -> ProgressEvent:
        event = ProgressEvent(task_id=task_id, state=self.states[task_id], note=note, pct=pct)
        self._audit("firstmate.progress", task_id, event.model_dump())
        return event

    def request_approval(
        self,
        task_id: str,
        kind: ApprovalKind,
        summary: str,
        preview: str = "",
        options: list[str] | None = None,
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            task_id=task_id, kind=kind, summary=summary, preview=preview, options=options or ["approve", "reject"]
        )
        self.approvals[req.id] = req
        self.states[task_id] = TaskState.awaiting_approval
        self._audit("firstmate.approval", task_id, req.model_dump())
        return req

    def resolve_approval(self, task_id: str, approval_id: str, decision: str, note: str = "") -> bool:
        req = self.approvals[approval_id]
        if req.resolved:
            raise PolicyError(f"approval {approval_id} already resolved")
        if decision not in req.options:
            raise PolicyError(f"decision '{decision}' not in options {req.options}")
        req.resolved = True
        req.decision = decision
        self.states[task_id] = TaskState.running
        self._audit(
            "firstmate.approval", task_id, {"event": "resolved", "id": approval_id, "decision": decision, "note": note}
        )
        return decision == "approve"

    def follow_up(self, task_id: str, body: str, dedupe_key: str) -> FollowUp | None:
        """Typed per-task follow-up. Same dedupe_key twice -> dropped (None)."""
        key = f"{task_id}:{dedupe_key}"
        if key in self._follow_up_keys:
            return None
        self._follow_up_keys.add(key)
        fu = FollowUp(task_id=task_id, body=body, dedupe_key=dedupe_key)
        self._audit("firstmate.follow_up", task_id, fu.model_dump())
        return fu

    # -- closeout -----------------------------------------------------------

    def finish(self, task_id: str, receipt: Receipt) -> Receipt:
        self.states[task_id] = TaskState.done
        self._audit("firstmate.receipt", task_id, receipt.model_dump())
        return receipt

    def fail(self, task_id: str, error: str):
        self.states[task_id] = TaskState.failed
        self._audit("firstmate.task", task_id, {"event": "failed", "error": error})

    def cancel(self, task_id: str):
        self.states[task_id] = TaskState.cancelled
        self._audit("firstmate.task", task_id, {"event": "cancelled"})
