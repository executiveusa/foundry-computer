import base64
import binascii
import hmac
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles

from .config import settings
from .models import *
from .runtime import BashRuntime, MockRuntime, UnsupportedAction
from .store import Store

app = FastAPI(
    title="Foundry Computer", version="0.1.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
)
store = Store(settings.database_path)


def _select_runtime():
    backend = settings.runtime_backend
    if backend == "bash":
        return BashRuntime()
    if backend == "opensandbox":
        from .opensandbox_runtime import OpenSandboxRuntime

        return OpenSandboxRuntime()
    return MockRuntime()


runtime = _select_runtime()


def _preview_authorized(request: Request) -> bool:
    if not settings.preview_password:
        return False
    header = request.headers.get("Authorization", "")
    if not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header.split(" ", 1)[1]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False
    return hmac.compare_digest(
        username.encode("utf-8", "ignore"), settings.preview_user.encode()
    ) and hmac.compare_digest(
        password.encode("utf-8", "ignore"), settings.preview_password.encode()
    )


@app.middleware("http")
async def protect_browser_preview(request: Request, call_next):
    path = request.url.path
    if path == "/healthz":
        return await call_next(request)
    if path.startswith("/api/") and path not in {"/api/docs", "/api/openapi.json"}:
        return await call_next(request)
    if not _preview_authorized(request):
        return Response(
            content="Foundry client preview requires authentication.",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Foundry Client Preview"'},
            media_type="text/plain",
        )
    return await call_next(request)


def auth(authorization: str | None = Header(default=None)):
    if not hmac.compare_digest(
        (authorization or "").encode("utf-8", "ignore"), f"Bearer {settings.api_key}".encode()
    ):
        raise HTTPException(401, "invalid bearer token")


def require(kind, id):
    value = store.get(kind, id)
    if not value:
        raise HTTPException(404, f"{kind} not found")
    return value


def pick_host(cpu, ram):
    hosts = [h for h in store.list("host") if not h.get("draining")]
    if not hosts:
        local = {
            "id": "local",
            "name": "local",
            "endpoint": "local",
            "cpu_total": 64,
            "ram_total_gb": 256,
            "draining": False,
        }
        store.put("host", "local", local)
        hosts = [local]
    computers = store.list("computer")
    for h in hosts:
        used_cpu = sum(
            c["cpu"] for c in computers if c["host_id"] == h["id"] and c["status"] == "running"
        )
        used_ram = sum(
            c["ram"] for c in computers if c["host_id"] == h["id"] and c["status"] == "running"
        )
        if used_cpu + cpu <= h["cpu_total"] and used_ram + ram <= h["ram_total_gb"]:
            return h
    raise HTTPException(409, "no host has safe capacity")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post(
    "/api/workspaces", response_model=Workspace, status_code=201, dependencies=[Depends(auth)]
)
def create_workspace(body: WorkspaceCreate):
    item = Workspace(id=str(uuid4()), name=body.name).model_dump()
    store.put("workspace", item["id"], item)
    return item


@app.get("/api/workspaces", dependencies=[Depends(auth)])
def list_workspaces():
    return store.list("workspace")


@app.get("/api/workspaces/{id}", dependencies=[Depends(auth)])
def get_workspace(id: str):
    return require("workspace", id)


@app.post("/api/computers", response_model=Computer, status_code=201, dependencies=[Depends(auth)])
def create_computer(body: ComputerCreate):
    require("workspace", body.workspace_id)
    if any(
        c["workspace_id"] == body.workspace_id and c["name"] == body.name
        for c in store.list("computer")
    ):
        raise HTTPException(409, "computer name already exists")
    host = pick_host(body.cpu, body.ram)
    id = str(uuid4())
    item = Computer(
        id=id,
        host_id=host["id"],
        url=f"/console/computers/{id}",
        **body.model_dump(exclude={"template_ref"}),
    ).model_dump()
    runtime.create(item)
    store.put("computer", id, item)
    store.event("computer.created", id, item)
    return item


@app.get("/api/computers", dependencies=[Depends(auth)])
def list_computers(workspace_id: str | None = None):
    return [
        c for c in store.list("computer") if not workspace_id or c["workspace_id"] == workspace_id
    ]


@app.get("/api/computers/{id}", dependencies=[Depends(auth)])
def get_computer(id: str):
    return require("computer", id)


@app.delete("/api/computers/{id}", status_code=204, dependencies=[Depends(auth)])
def delete_computer(id: str):
    c = require("computer", id)
    runtime.lifecycle(c, "delete")
    store.delete("computer", id)
    store.event("computer.deleted", id, {})
    return Response(status_code=204)


@app.get("/api/computers/{id}/screenshot", dependencies=[Depends(auth)])
def screenshot(id: str):
    try:
        return Response(runtime.screenshot(require("computer", id)), media_type="image/png")
    except UnsupportedAction as e:
        raise HTTPException(501, f"unsupported_action: {e.action} (no real runtime)") from e


def do_action(id, action, payload):
    c = require("computer", id)
    if c["status"] != "running":
        raise HTTPException(409, "computer is stopped")
    result = runtime.action(c, action, payload)
    if isinstance(result, dict) and result.get("error") == "mock_bash_disabled":
        raise HTTPException(403, "mock bash disabled (tests only)")
    if isinstance(result, dict) and result.get("error") == "unsupported_action":
        raise HTTPException(501, f"unsupported_action: {result.get('action')} (no real runtime)")
    store.event(f"computer.{action}", id, {"keys": list(payload)})
    return result


@app.post("/api/computers/{id}/click", dependencies=[Depends(auth)])
def click(id: str, body: Click):
    return do_action(id, "click", body.model_dump())


@app.post("/api/computers/{id}/type", dependencies=[Depends(auth)])
def type_text(id: str, body: TypeText):
    return do_action(id, "type", body.model_dump())


@app.post("/api/computers/{id}/key", dependencies=[Depends(auth)])
def key(id: str, body: KeyPress):
    return do_action(id, "key", body.model_dump())


@app.post("/api/computers/{id}/scroll", dependencies=[Depends(auth)])
def scroll(id: str, body: Scroll):
    return do_action(id, "scroll", body.model_dump())


@app.post("/api/computers/{id}/bash", dependencies=[Depends(auth)])
def bash(id: str, body: BashCommand):
    return do_action(id, "bash", body.model_dump())


@app.post("/api/computers/{id}/{action}", dependencies=[Depends(auth)])
def lifecycle(id: str, action: str):
    if action not in {"start", "stop", "restart"}:
        raise HTTPException(404)
    c = require("computer", id)
    rt = runtime.lifecycle(c, action)
    c["status"] = "stopped" if action == "stop" else "running"
    store.put("computer", id, c)
    store.event(f"computer.{action}", id, {})
    return {**c, "runtime": rt}


@app.post("/internal/hosts", dependencies=[Depends(auth)])
def register_host(body: HostRegister):
    id = str(uuid4())
    host = {"id": id, **body.model_dump(), "draining": False}
    store.put("host", id, host)
    return host


@app.post("/internal/hosts/{id}/drain", dependencies=[Depends(auth)])
def drain_host(id: str):
    host = require("host", id)
    host["draining"] = True
    store.put("host", id, host)
    return host


app.mount("/", StaticFiles(directory="web", html=True), name="web")
