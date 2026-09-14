import base64, subprocess
from abc import ABC, abstractmethod
PNG_1X1=base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")
class Runtime(ABC):
    @abstractmethod
    def create(self, computer: dict): ...
    @abstractmethod
    def lifecycle(self, computer: dict, action: str): ...
    @abstractmethod
    def action(self, computer: dict, action: str, payload: dict): ...
    def screenshot(self, computer: dict) -> bytes: return PNG_1X1
class MockRuntime(Runtime):
    def create(self, computer): return {"runtime_id": "mock-"+computer["id"]}
    def lifecycle(self, computer, action): return {"ok": True, "action": action}
    def action(self, computer, action, payload):
        if action == "bash":
            p=subprocess.run(["bash","-lc",payload["command"]],capture_output=True,text=True,timeout=payload.get("timeout_seconds",60))
            return {"stdout":p.stdout,"stderr":p.stderr,"exit_code":p.returncode}
        return {"ok":True,"action":action}
