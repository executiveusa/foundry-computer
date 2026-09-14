from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

def now() -> str:
    return datetime.now(timezone.utc).isoformat()
class WorkspaceCreate(BaseModel): name: str = Field(min_length=1, max_length=80)
class Workspace(BaseModel): id: str; name: str; status: str = "active"; created_at: str = Field(default_factory=now)
class ComputerCreate(BaseModel):
    workspace_id: str; name: str = Field(min_length=1, max_length=80); os: Literal["linux"] = "linux"
    ram: int = Field(default=4, ge=1, le=64); cpu: float = Field(default=1, ge=.5, le=16)
    disk_size_gb: int = Field(default=8, ge=1, le=512); resolution: str = "1280x720x24"; template_ref: str | None = None
class Computer(BaseModel):
    id: str; workspace_id: str; name: str; status: Literal["running","stopped","error"] = "running"
    os: str = "linux"; ram: int = 4; cpu: float = 1; disk_size_gb: int = 8; resolution: str = "1280x720x24"
    host_id: str; url: str; created_at: str = Field(default_factory=now)
class HostRegister(BaseModel):
    name: str; endpoint: str; cpu_total: float = Field(gt=0); ram_total_gb: int = Field(gt=0); labels: dict[str,str] = {}
class Click(BaseModel): x: int; y: int; button: str = "left"
class TypeText(BaseModel): text: str
class KeyPress(BaseModel): key: str
class Scroll(BaseModel): x: int = 0; y: int
class BashCommand(BaseModel): command: str = Field(min_length=1, max_length=20000); timeout_seconds: int = Field(default=60, ge=1, le=600)
