import os,tempfile
os.environ["FOUNDRY_DATABASE_PATH"]=tempfile.mktemp()
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
