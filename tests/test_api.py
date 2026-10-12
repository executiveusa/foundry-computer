import base64
import os,tempfile
os.environ["FOUNDRY_DATABASE_PATH"]=tempfile.mktemp()
os.environ["FOUNDRY_PREVIEW_USER"]="client"
os.environ["FOUNDRY_PREVIEW_PASSWORD"]="test-preview-only"
from fastapi.testclient import TestClient
from foundry.main import app
c=TestClient(app); H={"Authorization":"Bearer foundry-local-dev"}
def test_orgo_shaped_happy_path_and_persistence():
    w=c.post("/api/workspaces",headers=H,json={"name":"starnet"}); assert w.status_code==201
    comp=c.post("/api/computers",headers=H,json={"workspace_id":w.json()["id"],"name":"watcher"}); assert comp.status_code==201
    id=comp.json()["id"]
    assert c.get(f"/api/computers/{id}/screenshot",headers=H).headers["content-type"]=="image/png"
    assert c.post(f"/api/computers/{id}/bash",headers=H,json={"command":"printf foundry"}).json()["stdout"]=="foundry"
    assert c.post(f"/api/computers/{id}/stop",headers=H).json()["status"]=="stopped"
    assert c.post(f"/api/computers/{id}/start",headers=H).json()["status"]=="running"
def test_auth_and_duplicate_name():
    assert c.get("/api/workspaces").status_code==401
    w=c.post("/api/workspaces",headers=H,json={"name":"dup"}).json()
    body={"workspace_id":w["id"],"name":"same"}; assert c.post("/api/computers",headers=H,json=body).status_code==201
    assert c.post("/api/computers",headers=H,json=body).status_code==409


def test_browser_preview_requires_separate_basic_auth():
    assert c.get("/").status_code == 401
    basic = base64.b64encode(b"client:test-preview-only").decode()
    assert c.get("/", headers={"Authorization": f"Basic {basic}"}).status_code == 200
    assert c.get("/api/docs").status_code == 401
    assert c.get("/api/docs", headers={"Authorization": f"Basic {basic}"}).status_code == 200
