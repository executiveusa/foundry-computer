# Security status

Internal alpha, not a hostile public multi-tenant boundary. Do not expose to
the public internet without TLS, network policy, key rotation, runtime
sandboxing, independent review, and backups.

## BashRuntime (dev/test backend) - known holes, by design NOT fixed here

BashRuntime (`FOUNDRY_RUNTIME_BACKEND=bash`) exists for development and
contract tests. It is NOT an isolation boundary:

- Runs in the same container/failure domain as the control plane (root API
  process, API key env, sqlite DB on the same filesystem).
- No network restriction on executed commands.
- No cgroups: rlimits are per-uid/per-process, not aggregate; fork/memory
  pressure across runs is not capped as a group.
- A command that detaches via setsid/nohup escapes the process-group kill.
- Per-computer uids are sha256-derived and can theoretically collide
  (50k uid space); workdirs are per-computer but on shared /tmp.
- No filesystem cleanup of per-computer workdirs on computer stop/delete.

Real isolation is slice 2: per-computer rootless containers driven by a
separate least-privilege host daemon (docs/SLICE2_ROOTLESS_RUNTIME.md).

## MockRuntime

Executes shell on the control-plane host ONLY when FOUNDRY_DEV_MODE=true AND
FOUNDRY_MOCK_ALLOW_BASH=1 (contract tests). Otherwise bash is refused and
desktop/fs actions return 501 unsupported_action.

## Agent task loop (agent_s)

Default-deny permission hook; model output is never trusted as fact (a "done"
claim passes only after an independent verify call); raw tool output is
redacted to metadata before reaching any model endpoint; model calls are
capped per run; the model client activates only via explicit env config.
