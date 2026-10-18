# Foundry Computer

Self-hosted computers for AI agents. Foundry Computer gives agents persistent Linux desktops through an Orgo-shaped REST API while the operator owns the hosts and pays no per-computer software fee.

> Internal alpha. Public signup, billing, and multi-tenant hosting are intentionally disabled.

## Dev quickstart (control plane + bash-only dev backend)

```bash
cp .env.example .env
docker compose up --build
export ORGO_BASE_URL=http://localhost:8000/api
export ORGO_API_KEY="$(grep '^FOUNDRY_API_KEY=' .env | cut -d= -f2-)"
curl -X POST "$ORGO_BASE_URL/workspaces" -H "Authorization: Bearer $ORGO_API_KEY" -H 'Content-Type: application/json' -d '{"name":"starnet"}'
```

The API key comes from your `.env`; `foundry-local-dev` is only the fallback when `FOUNDRY_API_KEY` is unset.

What is real today: workspaces, computers (metadata + control-plane lifecycle), bash execution through the dev/test BashRuntime (uid-demoted, rlimits, timeout/output caps - NOT an isolation boundary, see SECURITY.md), the permission-hooked agent task loop (`src/foundry/agent_s.py`), and the Pauli Crawl router (`src/foundry/crawl.py`).

What is NOT real yet: screenshots, click/type/key/scroll, upload/download, VNC, templates, and actual machine provisioning. Those return 501 `unsupported_action`, and computer lifecycle reports runtime `unprovisioned`, until the slice-2 rootless runtime lands (docs/SLICE2_ROOTLESS_RUNTIME.md).

## Tests

```bash
docker run --rm -v "$PWD:/app" -w /app python:3.12-slim sh -c "pip install -q -e . pytest httpx ruff && python -m pytest tests/ -q && ruff check ."
```

Run as root in docker: the BashRuntime uid-demotion tests require root, so nothing is skipped. CI runs exactly this.

See [docs/architecture.md](docs/architecture.md), [docs/api-compatibility.md](docs/api-compatibility.md), and [SECURITY.md](SECURITY.md).
