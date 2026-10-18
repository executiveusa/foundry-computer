# Foundry Computer - P0 audit (read-only, 2026-10-18)
Method: GitHub API read of executiveusa/foundry-computer default branch (private). No clone, no test run (no baseline tests executed by the auditor; the desk must run `pytest -q` and record the result). Unverified = not done.

## Inventory (16 files)
src/foundry/{__init__,config,main,models,runtime,store}.py, web/{index.html,style.css}, tests/test_api.py (3 tests), docs/{architecture,api-compatibility}.md, SECURITY.md, Dockerfile, docker-compose.yml, Makefile, pyproject.toml (fastapi, uvicorn, pydantic-settings, httpx; dev pytest, ruff), .env.example, .github/workflows/test.yml (pip install + pytest only; no ruff, no docker build).
History: 1 closed PR (#1 "lock browser preview and API docs", not merged as PR). No open issues. No LICENSE file.

## Real vs mock
- REAL: FastAPI control plane; SQLite store (objects/events tables); workspaces and computers CRUD; host registration/drain and CPU/RAM capacity admission; audit events table (written, no read endpoint); Basic-auth preview gate for web UI and /api/docs.
- MOCK / FAKE: runtime.py MockRuntime is the only runtime. create/lifecycle return canned dicts, no process or container is started. screenshot returns a hardcoded 1x1 PNG. click/type/key/scroll return {"ok":true} and do nothing. "computer stopped/running" is only a DB field. Default host is a fabricated "local" host with 64 CPU / 256 GB. Computer url (/console/computers/id) points at nothing.
- DOCUMENTED BUT ABSENT: runtime agent, persistent volumes, VNC/viewer, WebSockets, drag/wait/python, file transfer, templates, scoped keys, OpenAI-compatible chat, SDKs, web console beyond a static page.
- Missing entirely vs the 2.0 handoff: isolated desktop runtime, live viewer, task engine/agent loop, Agent-S, Pauli Crawl, approvals, evidence/artifact store, CLI, MCP server, skills, Omarchy.

## Security findings
CRITICAL
1. MockRuntime bash runs `bash -lc <command>` on the control-plane host as the service user (arbitrary RCE for any bearer-key holder). SECURITY.md admits it. Must never ship in a deployed config; the real runtime must execute only inside the isolated computer.
2. Default API key "foundry-local-dev" in config.py and README; compose reads .env that may not exist. The service starts with the known default key if FOUNDRY_API_KEY is unset. Fail closed: refuse to start on default/short key outside dev mode.
HIGH
3. Bearer check is `authorization != f"Bearer {key}"` (non-constant-time). Use hmac.compare_digest.
4. Single global key, no scoping, no per-user/tenant ownership; any key holder sees all workspaces/computers.
5. /internal/hosts* is on the same key as the public API; host registration accepts arbitrary endpoint (SSRF/host takeover once real runtime dials endpoints). Needs separate host token.
6. Preview gate: if FOUNDRY_PREVIEW_PASSWORD is empty, UI is 401 for everyone (fail-closed, good). Basic auth over HTTP needs TLS in front.
MEDIUM
7. Store opens a new SQLite connection per call, reads unlocked, no migrations/versioning; capacity check-then-insert in create_computer is racy (no transaction), so over-admission is possible under concurrency.
8. Dockerfile runs as root, no HEALTHCHECK, no pinned base digest; `pip install .` before copying src (fine) but no lockfile.
9. Events log only payload keys for actions (good, no secret leak) but there is no auth identity in events and no read API.
10. bash action has no output size cap (stdout/stderr unbounded) and timeout raises unhandled TimeoutExpired -> 500.
11. `from .models import *`; no CORS config (ok), no rate limiting, no request size limits.
12. Lifecycle route `/{action}` catch-all shares prefix with real routes; fine now, fragile when adding routes.
LICENSE: none. Repo is private/internal; the handoff intends to sell it. Decide license before any public release. Dependencies planned (Agent-S Apache-2.0, Omarchy MIT, cua MIT per prior notes) must be re-verified against upstream LICENSE files at pin time, not from memory.

## Tests
3 tests: happy path via mock, auth+duplicate name, preview auth. They prove API contract only, nothing about a real computer. CI runs the same pytest. No coverage of: capacity admission, drain, 404s, delete, malformed input, timeout, concurrency.

## Recommended P0 order (agrees with handoff)
1. Run baseline `pytest -q` + `ruff check`; record counts. 2. Branch protection on main (needs repo admin; note PR-only flow). 3. Commit this audit under docs/audit/. 4. Fix CRITICAL 2, HIGH 3 and MEDIUM 10 (small, testable). 5. Build real runtime behind the existing Runtime ABC: one rootless container (Xvfb + window manager + noVNC/x11vnc + Chromium) per computer, bash/click/type/key/scroll/screenshot executed inside it via xdotool/scrot, named volume for persistence, resource limits, no host mount, no privileged mode, no docker.sock exposure to the container. 6. Gate MockRuntime behind FOUNDRY_RUNTIME=mock only in tests; the deployed default must be the real runtime. 7. Tests that fail if the runtime is mock: screenshot is not the 1x1 PNG; a file typed into a computer survives stop/start; bash in computer cannot read control-plane DB or host files.
Resource note: a desktop container needs roughly 1 GB RAM + 1 vCPU. prod-city-1 has ~700 MB free, so the real-runtime test must run on a different host; any rental needs Bambu's exact-amount approval.

## Baseline verification (server desk, 2026-10-18, docker python:3.12-slim on prod-city-1)
- `pytest -q`: 3 passed, 0 failed (0.65s). Baseline green.
- `ruff check src tests`: 9 errors, 8 auto-fixable (import sorting/unused; no logic findings). Not yet fixed; fix belongs in the CRITICAL-fix slice.
- Environment note: tests and lint ran in a throwaway container; nothing installed on the host.
