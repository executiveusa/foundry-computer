"""Agent-S adapter (P1): observe -> interpret -> permission -> act -> verify.

Honest scope: this is the Foundry-side adapter and execution loop. The real
Agent-S3 engine and visual grounding plug in behind the model client; desktop
actions require a real computer runtime (slice 2 - the mock/bash backends
return unsupported_action and the loop escalates). No model is called unless
explicitly configured via FOUNDRY_AGENT_MODEL_* env vars, so nothing spends
money by importing this module. Tests use stubs, never the network.
"""

import json
import os
from typing import ClassVar

import httpx

from .runtime import UnsupportedAction


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

    def __init__(self, runtime, model, permission=None, max_steps=20):
        self.runtime = runtime
        self.model = model
        # default-deny: no permission hook means nothing executes
        self.permission = permission or (lambda computer, action, payload: False)
        self.max_steps = max_steps

    def _observe(self, computer):
        try:
            shot = self.runtime.screenshot(computer)
            available = isinstance(shot, bytes) and len(shot) > 0
        except (UnsupportedAction, RuntimeError, OSError):
            available = False
        return {"screenshot_available": available, "computer": computer.get("name")}

    def run(self, computer, task):
        history = []
        for step in range(self.max_steps):
            obs = self._observe(computer)
            reply = self.model.complete(
                [
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "task": task,
                                "observation": obs,
                                "recent_history": history[-5:],
                            }
                        ),
                    }
                ]
            )
            try:
                plan = json.loads(reply)
            except json.JSONDecodeError:
                history.append({"step": step, "error": "unparseable_model_reply"})
                continue
            if plan.get("done"):
                return {
                    "status": "done",
                    "steps": step,
                    "summary": plan.get("summary", ""),
                    "history": history,
                }
            action, payload = plan.get("action"), plan.get("payload", {})
            if action not in self.ACTIONS:
                return {
                    "status": "escalated",
                    "reason": f"unknown action: {action}",
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
            history.append({"step": step, "action": action, "result": result})
            if isinstance(result, dict) and result.get("error") == "unsupported_action":
                return {
                    "status": "escalated",
                    "reason": f"runtime cannot '{action}' (needs a real runtime)",
                    "history": history,
                }
        return {"status": "max_steps", "history": history}
