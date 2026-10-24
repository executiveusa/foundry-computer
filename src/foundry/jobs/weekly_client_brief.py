"""First managed job: weekly client research + brief for an agency.

Draft-only BY POLICY: the task's allowed verbs are research, read and
write_draft. Send, email, publish, post and spend are not in the policy, so
the first-mate gateway refuses them - the job can never contact anyone or
push anything live. Output is a markdown brief with a Sources section, plus
a Receipt (the end-of-shift report): actions, tokens, cost, sources,
artifacts. The model is any OpenAI-compatible chat model the operator picks;
the researcher is injectable (in production: the crawl router + web through
the sandbox; in tests: a stub, never the network).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..firstmate import CapExceeded, Caps, FirstMate, PolicyError, Receipt, TaskSpec

JOB_NAME = "weekly-client-brief"

_SYSTEM = (
    "You are a research analyst for an agency. Write a concise weekly client brief "
    "in markdown. Every claim that comes from a source must cite it inline as [n]. "
    "End with a '## Sources' section listing every cited URL. Never invent sources. "
    "This is a DRAFT for a human to review and send - start the document with the "
    "line '> DRAFT - not sent.'"
)


def make_task(client: str, topics: list[str], caps: Caps | None = None, **inputs) -> TaskSpec:
    return TaskSpec(
        job=JOB_NAME,
        inputs={"client": client, "topics": topics, **inputs},
        allowed_verbs={"research", "read", "write_draft"},
        caps=caps or Caps(),
    )


def run(
    task: TaskSpec,
    mate: FirstMate,
    model: Any,
    researcher: Callable[[str, list[str]], list[dict]],
) -> Receipt:
    """Run one draft-only weekly brief. Returns the Receipt either way."""
    mate.start(task.id)
    started = mate._started[task.id]
    sources: list[str] = []
    artifacts: list[str] = []
    over_caps = False
    try:
        mate.authorize(task.id, "research")
        mate.progress(task.id, "researching", pct=10)
        findings = researcher(task.inputs["client"], task.inputs["topics"])
        mate.record_usage(task.id, actions=1)
        sources = [f["url"] for f in findings if f.get("url")]
        if not sources:
            raise RuntimeError("researcher returned no citable sources; refusing to write on vibes")

        mate.authorize(task.id, "write_draft")
        mate.progress(task.id, "drafting", pct=60)
        notes = "\n".join(
            f"- [{i + 1}] {f.get('title', '')}: {f.get('note', '')} ({f['url']})"
            for i, f in enumerate(findings)
            if f.get("url")
        )
        messages = [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Client: {task.inputs['client']}\n"
                    f"Topics: {', '.join(task.inputs['topics'])}\n"
                    f"Research notes:\n{notes}\n\nWrite this week's brief."
                ),
            },
        ]
        draft = model.complete(messages)
        usage = getattr(model, "last_usage", None) or {}
        tokens = (
            int(usage.get("total_tokens", 0))
            or (sum(len(m["content"]) for m in messages) + len(draft)) // 4
        )
        cost = float(usage.get("cost_usd", 0.0))
        mate.record_usage(task.id, actions=1, tokens=tokens, cost_usd=cost)

        artifact_id = f"brief-{task.id}"
        if mate.store is not None:
            mate.store.put(
                "artifact",
                artifact_id,
                {
                    "task_id": task.id,
                    "job": task.job,
                    "kind": "markdown_draft",
                    "body": draft,
                },
            )
        artifacts.append(artifact_id)
        mate.progress(task.id, "draft ready for human review", pct=100)
        receipt = Receipt(
            task_id=task.id,
            job=task.job,
            started_at=started,
            actions=mate.usage(task.id).actions,
            tokens=mate.usage(task.id).tokens,
            cost_usd=mate.usage(task.id).cost_usd,
            models=[getattr(model, "model", "unknown")],
            sources=sources,
            artifacts=artifacts,
            caps=task.caps,
            draft_only=True,
            notes="draft stored; nothing sent",
        )
        return mate.finish(task.id, receipt)
    except (CapExceeded, PolicyError, RuntimeError) as e:
        over_caps = isinstance(e, CapExceeded)
        mate.fail(task.id, str(e))
        return Receipt(
            task_id=task.id,
            job=task.job,
            started_at=started,
            actions=mate.usage(task.id).actions,
            tokens=mate.usage(task.id).tokens,
            cost_usd=mate.usage(task.id).cost_usd,
            models=[getattr(model, "model", "unknown")],
            sources=sources,
            artifacts=artifacts,
            caps=task.caps,
            over_caps=over_caps,
            draft_only=True,
            notes=f"failed: {e}",
        )
