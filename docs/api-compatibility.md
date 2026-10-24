# Orgo compatibility target

Implemented now (real): workspaces; create/list/get/delete computers;
start/stop/restart (control-plane state; the dev backend reports
runtime "unprovisioned" - no machine exists); bash via the dev/test
BashRuntime (uid-demoted, capped, dev only).

Honestly NOT implemented - these return 501 unsupported_action until a real
runtime (slice 2) backs them: screenshot, click, type, key, scroll, drag,
wait, open_url, upload/download, VNC, clone/resize, templates, WebSockets.

Next: slice-2 rootless runtime, scoped keys, OpenAI-compatible computer-use
chat. Compatibility is tested by changing only base URL and bearer key in an
existing StarNet workflow.
