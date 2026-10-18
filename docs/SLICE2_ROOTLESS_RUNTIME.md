# Slice 2: Per-Computer Rootless Runtime (design)

Status: DESIGN ONLY. Not built. This note exists so the jump from the dev
backend to a real computer runtime is reviewable before code.

## Why

`BashRuntime` (merged as dev/test only) runs commands on the control-plane
host. Its own docstring lists the holes: setsid/nohup escape, rlimits are
per-uid not aggregate, no network restriction, same failure domain as the API.
It must never run untrusted work. Slice 2 is the real boundary.

## Shape

```
API (control plane, no privileged execution)
   |  unix socket / localhost HTTP, per-computer tokens
   v
foundry-hostd (separate daemon, owns podman socket)
   |  creates/destroys
   v
one rootless container per computer (podman, userns=auto)
   - own uid map (container root -> unprivileged host uid range)
   - cgroups v2: memory/pids/cpu limits (aggregate, enforced by kernel)
   - network: none by default; opt-in allow-list proxy (pypi/github shapes)
   - read-only rootfs + per-computer writable volume (/work)
   - no host mounts, no docker.sock, no secrets in env
```

Desktop actions come from the image: Xvfb + Chromium + xdotool (or
Playwright's controlled Chromium), exposed to the control plane through the
container's agent process - never through host input injection.

## Rules

1. The control plane never executes task commands. It talks to foundry-hostd.
2. foundry-hostd does exactly one thing: reconcile computer records to
   rootless containers. No business logic, no database access.
3. One computer = one container = one uid map = one volume. No sharing.
4. A command that escapes its session/process group is still inside the
   container's cgroup and network policy. Container teardown is the mop.
5. Everything runs off prod-city-1 until proven (capacity + soak); production
   deploy is a separate gate with the owner.

## Honest cost/limit notes

- Rootless podman networking limits egress policy to what slirp4netns/pasta
  allow; the allow-list proxy (tiny forward proxy in a sidecar network) is
  the clean enforcement point, not iptables inside the container.
- First slice targets shell + HTTP actions; GUI/desktop lands when the image
  is proven, and stays behind the same action contract (no new API).
- Screenshot/click/type ship only when backed by the real desktop; until then
  the API keeps returning 501 unsupported_action.

## Test plan (before any merge)

- Escape tests: setsid/nohup detach, fork bomb (cgroup pids), memory hog
  (cgroup oom), outbound curl to non-allow-listed host (must fail), host path
  probe (must see nothing), sibling computer probe (must see nothing).
- Soak: 100 create/run/stop/delete cycles, no leaked containers/volumes.
- Chaos: hostd restart mid-task; container killed externally; full disk.
- All of it on a throwaway VM/pod, never on prod-city-1.
