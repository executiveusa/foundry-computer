# Foundry Computer

Self-hosted computers for AI agents. Foundry Computer gives agents persistent Linux desktops through an Orgo-shaped REST API while the operator owns the hosts and pays no per-computer software fee.

> Internal alpha. Public signup, billing, and multi-tenant hosting are intentionally disabled.

## First proof

```bash
cp .env.example .env
docker compose up --build
export ORGO_BASE_URL=http://localhost:8000/api
export ORGO_API_KEY=foundry-local-dev
curl -X POST "$ORGO_BASE_URL/workspaces" -H "Authorization: Bearer $ORGO_API_KEY" -H 'Content-Type: application/json' -d '{"name":"starnet"}'
```

The compatibility surface covers workspaces, computers, lifecycle, screenshots, pointer/keyboard input, shell execution, persistence, host registration and capacity admission.

See [docs/architecture.md](docs/architecture.md), [docs/api-compatibility.md](docs/api-compatibility.md), and [SECURITY.md](SECURITY.md).
