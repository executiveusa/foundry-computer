# OpenSandbox pilot runbook (VPS)

Goal: prove one real isolated sandbox behind Foundry on the existing
Hostinger VPS, then the desktop image, then one draft-only job. No spend.
If a step needs KVM hardware, STOP and ask Bambu.

## 0. Prereq checks (5 min, read-only)

```bash
docker --version                      # need Docker on the VPS
sudo sh -c 'apt-get install -y runsc' # gVisor; skip if already present
runsc --version
ls /dev/kvm 2>/dev/null               # only needed for Firecracker (later)
```

If gVisor cannot run on this kernel, Docker-only still works for the pilot
but is NOT an isolation boundary - say so in the report and do not put
client data in it.

## 1. OpenSandbox server

```bash
uv pip install opensandbox-server
opensandbox-server init-config ~/.sandbox.toml --example docker
```

Edit `~/.sandbox.toml`:

```toml
[server]
api_key = "<long-random-key>"        # REQUIRED. No key = unauthenticated RCE.

[secure_runtime]
# enable gVisor (runsc) here per docs/getting-started/configuration.md
```

Run: `opensandbox-server` (default :8080). Verify:
`curl -H "OPEN-SANDBOX-API-KEY: <key>" http://127.0.0.1:8080/v1/sandboxes`

## 2. Foundry wiring (.env)

```
FOUNDRY_RUNTIME_BACKEND=opensandbox
FOUNDRY_OPENSANDBOX_DOMAIN=127.0.0.1:8080
FOUNDRY_OPENSANDBOX_API_KEY=<same key>
FOUNDRY_OPENSANDBOX_DEFAULT_IMAGE=opensandbox/desktop:latest
FOUNDRY_OPENSANDBOX_EGRESS_ALLOWLIST=api.openai.com   # only what the job needs
```

Foundry refuses to start with the backend selected and no key outside dev
mode (fail-closed, tested).

## 3. Desktop image

```bash
git clone https://github.com/opensandbox-group/OpenSandbox
cd OpenSandbox/examples/desktop && docker build -t opensandbox/desktop:latest .
```

noVNC must sit behind Foundry's preview auth (or a TLS proxy that injects
`OPEN-SANDBOX-API-KEY`); never expose a bare http noVNC port publicly
(their own desktop doc warns about mixed content + auth).

## 4. Prove it (the gauntlet for this pilot)

1. `POST /api/computers` through Foundry -> runtime reports
   `backend=opensandbox`, egress `deny-all-except-allowlist`.
2. bash action: `echo hi` returns stdout. `curl https://example.com` from
   inside FAILS (deny-all); an allowlisted domain succeeds.
3. stop/start/delete map to pause/resume/kill.
4. Isolation spot-check: sandbox cannot reach the host's metadata or
   internal services beyond the allowlist.
5. One real weekly-client-brief job end to end: draft markdown + Sources +
   Receipt in the audit log. Nothing sent anywhere.
6. Screenshot/click/type return the honest 501 `unsupported_action`.

## 5. Soak then decide

Run the brief job daily for a week with Orgo as fallback. Then decide
KVM/Firecracker (~$12.99/mo, Bambu's call) with failure data in hand.

## Rollback

Set `FOUNDRY_RUNTIME_BACKEND=bash` (or `mock`) and restart. The branch
changes nothing about the default backend.
