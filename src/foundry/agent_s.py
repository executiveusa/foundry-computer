"""Agent task loop (P1): observe -> interpret -> permission -> act -> verify.

Honest scope: this is the Foundry-side task loop behind the Agent-S adapter
contract - it is NOT a wired-in Agent-S3 engine. The model client is a minimal
OpenAI-compatible chat shape configured ONLY via env (FOUNDRY_AGENT_MODEL_*),
so importing this module spends nothing. Desktop actions escalate until a real
computer runtime (slice 2) exists. A "done" claim from the model is accepted
only after a separate verification pass. Tests use stubs, never the network.
"""

import json
import os
from typing import ClassVar

import httpx

from .runtime import UnsupportedAction

_SAFE_RESULT_KEYS = ("ok", "error", "exit_code", "truncated", "action")


class OpenAICompatibleModel:
    """Minimal OpenAI-compatible chat client (Anthropic/OpenRouter/local all
    expose this shape). Config comes only from env or explicit kwargs."""

    def __init__(self, base_url=None, api_key=None, model=None):
        self.base_url = (base_url or os.environ.get("FOUNDRY_AGENT_MODEL_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("FOUNDRY_AGENT_MODEL_API_KEY", "")
        self.model = model or os.environ.get("FOUNDRY_AGENT_MODEL", "")
        if not (self.base_url and self.model):
            raise RuntimeError(
                "agent model not configured (FOUNDRY_AGENT_MODEL_BASE_URL / FOUNDRY_AGENT_MODEL)"
            )

    def complete(self, messages):
        r = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": messages, "temperature": 0},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


class AgentSAdapter:
    """Runs one task against one computer through the runtime abstraction."""

    ACTIONS: ClassVar[frozenset] = frozenset(
        {
            "click",
            "move",
            "scroll",
            "type",
            "key",
            "drag",
            "wait",
            "open_url",
            "bash",
            "screenshot",
        }
    )

    def __init__(self, runtime, model, permission=None, max_steps=20, max_model_calls=40):
        self.runtime = runtime
        self.model = model
        # default-deny: no permission hook means nothing executes
        self.permission = permission or (lambda computer, action, payload: False)
        self.max_steps = max_steps
        self.max_model_calls = max_model_calls
        self._calls = 0

    def _ask(self, content):
        self._calls += 1
        return self.model.complete([{"role": "user", "content": content}])

    @staticmethod
    def _parse(reply):
        try:
            plan = json.loads(reply)
        except (json.JSONDecodeError, TypeError):
            return None
        return plan if isinstance(plan, dict) else None

    @staticmethod
    def _redact(result):
        """Only metadata reaches the model endpoint - never raw tool output."""
        if not isinstance(result, dict):
            return {"ok": bool(result)}
        return {k: result[k] for k in _SAFE_RESULT_KEYS if k in result}

    def _observe(self, computer):
        try:
            shot = self.runtime.screenshot(computer)
            available = isinstance(shot, bytes) and len(shot) > 0
        except (UnsupportedAction, RuntimeError, OSError):
            available = False
        return {"screenshot_available": available, "computer": computer.get("name")}

    def _verify(self, task, history):
        """A 'done' claim is accepted only after an independent verify pass."""
        reply = self._ask(
            json.dumps(
                {
                    "verify_task": task,
                    "claimed_done": True,
                    "outcome": history[-3:],
                }
            )
        )
        v = self._parse(reply)
        if v and v.get("verified") is True:
            return True, str(v.get("summary", ""))
        return False, ""

    def run(self, computer, task):
        history = []
        for step in range(self.max_steps):
            if self._calls >= self.max_model_calls:
                return {"status": "budget_exceeded", "history": history}
            reply = self._ask(
                json.dumps(
                    {
                        "task": task,
                        "observation": self._observe(computer),
                        "recent_history": history[-5:],
                    }
                )
            )
            plan = self._parse(reply)
            if plan is None:
                history.append({"step": step, "error": "unparseable_model_reply"})
                continue
            if plan.get("done"):
                verified, summary = self._verify(task, history)
                if verified:
                    return {"status": "done", "steps": step, "summary": summary, "history": history}
                history.append({"step": step, "done_rejected": "verification_failed"})
                continue
            action, payload = plan.get("action"), plan.get("payload", {})
            if action not in self.ACTIONS:
                return {
                    "status": "escalated",
                    "reason": f"unknown action: {action}",
                    "history": history,
                }
            if not isinstance(payload, dict):
                return {
                    "status": "escalated",
                    "reason": "invalid payload (must be an object)",
                    "history": history,
                }
            if not self.permission(computer, action, payload):
                history.append({"step": step, "action": action, "blocked": "permission_denied"})
                return {
                    "status": "blocked",
                    "reason": "permission_denied",
                    "action": action,
                    "history": history,
                }
            result = self.runtime.action(computer, action, payload)
            history.append({"step": step, "action": action, "result": self._redact(result)})
            if isinstance(result, dict) and result.get("error") == "unsupported_action":
                return {
                    "status": "escalated",
                    "reason": f"runtime cannot '{action}' (needs a real runtime)",
                    "history": history,
                }
        return {"status": "max_steps", "history": history}
