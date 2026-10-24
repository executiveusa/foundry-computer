# Foundry AI Employee - one-build plan (2026-10-19)

Status: PILOT BRANCH (`pilot/opensandbox-ai-employee`, base `feat/real-runtime`).
Everything below separates REAL (code + tests on this branch) from DESIGNED
(not built) and BLOCKED (needs Bambu).

## What we sell

One managed job, not "we cloned CellCog": a weekly client-research-and-brief
employee for agencies. Draft-only: it researches, cites sources, writes the
brief; a human reviews and sends. Every run ends with a receipt (actions,
tokens, cost, sources). Usage caps are enforced, not promised.

Test price hypothesis: $1,500 setup + $499/mo. Demand is NOT proven; that
number is an experiment, not a claim.

## What CellCog actually is (teardown facts)

A named, scheduled AI employee with memory, a task board, approvals and
end-of-shift receipts. Its $8 starter is credits, not unlimited labor; its own
billing guide says spending credits does not guarantee usable output. We sell
the same shape with one honest difference: caps and receipts are in the
control plane, so the buyer can verify them.
Source: https://cellcog.ai/support/billing-guide

## The one build

```
first mate (supervising agent, any model)          human approver
        | typed follow-ups / approvals / progress        |
        v                                                v
+--------------------- Foundry control plane ------------------------+
| firstmate.py  (protocol: tasks, approvals, caps, receipts, audit)  |
| jobs/weekly_client_brief.py  (draft-only policy, sources required) |
| agent_s.py task loop (any OpenAI-compatible model, per-task choice)|
| API: workspaces / computers / audit / fleet wall (existing)        |
+----------------------------+---------------------------------------+
                             | Runtime ABC
              +--------------+---------------+
              | OpenSandboxRuntime (NEW)     | MockRuntime / BashRuntime (dev)
              v                              v
     OpenSandbox server              (contract tests only)
     Docker + gVisor/Kata -> desktop image (Xvfb+XFCE+noVNC)
     egress: default-deny + per-job allowlist; credential vault
```

- Control plane: Foundry as it exists (auth, workspaces, computers, audit
  events, fleet wall). Orgo-shaped API kept for compatibility.
- Runtime: OpenSandbox (Apache-2.0) behind the Runtime ABC. REAL on this
  branch with a stubbed SDK; live against a server only after the VPS pilot.
  Isolation honesty: plain Docker is NOT a boundary - gVisor or Kata is
  required; Firecracker needs KVM hardware (the ~$12.99/mo spend gate,
  Bambu's call).
- Worker models: any OpenAI-compatible endpoint, chosen per task (cheap
  model for research, stronger model for the brief). Configured by env, no
  vendor lock.
- First mate: `firstmate.py` is a protocol + reference implementation. An
  Instinct-style agent supervises through it (approve/reject, typed
  follow-ups with dedupe, per-task progress, receipts). It is NOT a bundled
  Instinct; provisioning Instinct for clients is unsupported and unclaimed.
- Voice (later): borrow the typed per-task follow-up/approval/progress
  patterns (MIT hermes-voice-ios) into the existing Command Center WebRTC
  voice. No new app. It is OpenAI/iPhone-shaped, not Grok.
- Fallback: Orgo stays the backup desktop until a one-week soak passes.
  No client data on Orgo until the resale and disk-persistence questions are
  answered in writing (drafts ready for Bambu).

## Reuse ledger (licenses checked)

| Piece | License | Use |
|---|---|---|
| opensandbox-group/OpenSandbox | Apache-2.0 | Backend (vendored via pip extra) |
| CopilotKit/OpenBot | MIT, alpha | Ideas only (gateway-before-action, audit-first, takeover). Not a dependency; needs CopilotKit service; browser-only |
| nickvasilescu/hermes-voice-ios | MIT, public alpha | Patterns: typed follow-ups, approvals, progress, dedupe |
| nickvasilescu/firstmate | MIT | Studied; it is coding-agent orchestration (tmux/SSH), not our bridge |
| Nick's no-license repos | none | NO reuse |
| trycua/cua hosted cloud | ended 2026-10-18 | Skip hosted Cua |

## Phases (AI time, not human time)

- Phase 0 - THIS BRANCH (done): adapter + protocol + job + tests, all with
  stubs. 34/34 tests pass, ruff clean. No network, no spend.
- Phase 1 - VPS pilot (~2-4 agent-hours + wall-clock image pulls): OpenSandbox
  server on the Hostinger VPS with its API key set, Docker + gVisor, desktop
  image, Foundry pointed at it, one real draft-only job end to end with a
  receipt. Runbook: docs/OPENSANDBOX_PILOT.md. Prereq check first: does the
  VPS kernel support gVisor (runsc)? If not, that is the KVM decision.
- Phase 2 - Soak (one week wall-clock): daily brief job, Orgo as fallback,
  measure failures. Then the KVM/Firecracker decision with data.
- Phase 3 - Offer: MACS Digital Media one-pager (drafted, needs Bambu's yes
  before ANY contact). Price test only after one real draft-only job has run.

## Guardrails (standing, from Bambu)

No spend without his yes. No emails ever. Draft-only jobs - the policy
refuses send/publish/post/spend verbs. No client data on Orgo. No
Instinct-bundling claims. "Foolproof" is never claimed. Price is labeled a
hypothesis until a buyer pays.
