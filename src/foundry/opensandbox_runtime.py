"""OpenSandbox runtime backend (pilot): real isolated sandboxes behind the
Foundry Runtime ABC.

Honest scope:
- REAL in this module: sandbox create/pause/resume/kill and bash execution
  through the official OpenSandbox Python SDK, with a default-deny egress
  policy and a per-sandbox lifetime. Isolation strength is whatever the
  OpenSandbox SERVER is configured for: plain Docker is not a security
  boundary. Use [secure_runtime] with gVisor or Kata (Firecracker needs KVM
  hardware). See docs/OPENSANDBOX_PILOT.md.
- NOT real yet: screenshot, click/type/key/scroll, file upload/download.
  Those raise UnsupportedAction (the API answers a consistent 501) until the
  desktop slice lands.
- The opensandbox package is an optional dependency. Importing this module
  installs nothing and spends nothing; the SDK is imported lazily on first
  use. Tests inject a fake factory and never touch the network.
"""

from datetime import timedelta
from typing import Any

from .config import settings
from .runtime import Runtime, UnsupportedAction, _cap

# Foundry lifecycle verb -> OpenSandbox handle method
_LIFECYCLE = {"stop": "pause", "start": "resume", "delete": "kill"}


def _normalize_execution(result: Any) -> dict:
    """Shape an OpenSandbox Execution into Foundry's bash result contract."""
    logs = getattr(result, "logs", None)

    def _text(stream: str) -> str:
        msgs = getattr(logs, stream, None) if logs is not None else None
        if not msgs:
            return ""
        return "".join(getattr(m, "text", "") for m in msgs)

    stdout, t1 = _cap(_text("stdout"))
    stderr, t2 = _cap(_text("stderr"))
    out = {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": getattr(result, "exit_code", None),
        "truncated": t1 or t2,
    }
    error = getattr(result, "error", None)
    if error:
        out["error"] = str(getattr(error, "value", error))
    return out


def _default_factory():
    """Build the real SDK-backed sandbox factory (lazy import)."""
    try:
        from opensandbox.config.connection_sync import ConnectionConfigSync
        from opensandbox.models.sandboxes import NetworkPolicy, NetworkRule
        from opensandbox.sync.sandbox import SandboxSync
    except ImportError as e:  # pragma: no cover - exercised only without the extra
        raise RuntimeError(
            "opensandbox package not installed; install with "
            "`pip install foundry-computer[opensandbox]` (or `pip install opensandbox`)"
        ) from e

    def factory(*, image, timeout_minutes, env, metadata, resource, network_policy):
        cfg = ConnectionConfigSync(
            api_key=settings.opensandbox_api_key or None,
            domain=settings.opensandbox_domain,
            protocol=settings.opensandbox_protocol,
        )
        policy = NetworkPolicy(
            defaultAction="deny",
            egress=[NetworkRule(action="allow", target=t) for t in network_policy],
        )
        return SandboxSync.create(
            image=image,
            timeout=timedelta(minutes=timeout_minutes),
            env=env,
            metadata=metadata,
            resource=resource,
            network_policy=policy,
            connection_config=cfg,
        )

    return factory


class OpenSandboxRuntime(Runtime):
    """Maps a Foundry computer to one OpenSandbox sandbox."""

    def __init__(self, factory=None, allowlist=None, default_image=None, timeout_minutes=None):
        self._factory = factory or _default_factory()
        self._allowlist = (
            allowlist
            if allowlist is not None
            else [d.strip() for d in settings.opensandbox_egress_allowlist.split(",") if d.strip()]
        )
        self._default_image = default_image or settings.opensandbox_default_image
        self._timeout_minutes = timeout_minutes or settings.opensandbox_timeout_minutes
        self._sandboxes: dict[str, Any] = {}

    def create(self, computer: dict):
        image = computer.get("template_ref") or self._default_image
        handle = self._factory(
            image=image,
            timeout_minutes=self._timeout_minutes,
            env={},
            metadata={
                "foundry_computer_id": computer["id"],
                "foundry_workspace_id": computer.get("workspace_id", ""),
            },
            resource={"cpu": str(computer.get("cpu", 1)), "memory": f"{computer.get('ram', 4)}Gi"},
            network_policy=self._allowlist,
        )
        sandbox_id = getattr(handle, "id", None) or getattr(handle, "sandbox_id", None)
        runtime_id = f"osb-{sandbox_id}"
        self._sandboxes[runtime_id] = handle
        return {
            "runtime_id": runtime_id,
            "backend": "opensandbox",
            "image": image,
            "egress": "deny-all-except-allowlist",
            "isolation": "server-configured (use secure_runtime: gVisor/Kata; plain Docker is not a boundary)",
        }

    def _handle(self, computer: dict):
        runtime_id = computer.get("runtime_id") or ""
        handle = self._sandboxes.get(runtime_id)
        if handle is None:
            raise UnsupportedAction(f"no live sandbox for {runtime_id or computer.get('id')}")
        return handle

    def lifecycle(self, computer: dict, action: str):
        method = _LIFECYCLE.get(action)
        if method is None:
            raise UnsupportedAction(f"lifecycle:{action}")
        handle = self._handle(computer)
        getattr(handle, method)()
        return {"status": action, "action": action, "backend": "opensandbox"}

    def action(self, computer: dict, action: str, payload: dict):
        if action != "bash":
            raise UnsupportedAction(action)
        handle = self._handle(computer)
        result = handle.commands.run(
            payload["command"], timeout=timedelta(seconds=payload.get("timeout_seconds", 60))
        )
        return _normalize_execution(result)
