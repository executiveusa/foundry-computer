"""Pauli Crawl (P2): strategy router + result contract.

Honest scope: this module routes crawl tasks to the right engine and defines
the result schema. Real engines (Crawl4AI, Crawlee, Scrapling, Skyvern, Maxun)
plug in as adapters; an engine is available only when its adapter reports
healthy AND its feature flag is on (FOUNDRY_CRAWL_ENGINES=crawl4ai,crawlee).
Unavailable work returns a structured error - content is never fabricated and
unsuccessful extractions are never marked successful.
"""

import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import ClassVar

SCHEMA_VERSION = 1


@dataclass
class CrawlResult:
    job_id: str
    source_url: str
    retrieved_at: float
    engine: str
    status: str  # "success" | "failed" | "blocked"
    content_hash: str = ""
    extracted_data: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "source_url": self.source_url,
            "retrieved_at": self.retrieved_at,
            "engine": self.engine,
            "status": self.status,
            "content_hash": self.content_hash,
            "extracted_data": self.extracted_data,
            "evidence": self.evidence,
            "errors": self.errors,
            "schema_version": self.schema_version,
        }


def hash_content(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class EngineAdapter:
    """Contract every crawl engine adapter must satisfy."""

    name: str
    capabilities: ClassVar[set] = set()

    def available(self) -> bool:
        return self.name in enabled_engines()

    def health(self) -> dict:
        return {"engine": self.name, "available": self.available()}


def enabled_engines() -> set:
    return {e.strip() for e in os.environ.get("FOUNDRY_CRAWL_ENGINES", "").split(",") if e.strip()}


# routing table, most specific first; "interactive" stays last and flagged
_RULES = [
    (lambda t: t.get("interactive"), "skyvern"),
    (lambda t: t.get("schema") is not None, "scrapling"),
    (lambda t: t.get("kind") in {"site", "map", "batch"}, "crawlee"),
]
_DEFAULT = "crawl4ai"


def route(task: dict, available: set | None = None) -> str:
    """Pick the engine for a task; falls back through the table when the
    preferred engine is unavailable. Raises LookupError when nothing can
    serve the task (never silently picks a wrong-shaped engine)."""
    avail = enabled_engines() if available is None else available
    order = [e for pred, e in _RULES if pred(task)] + [_DEFAULT]
    for engine in order:
        if engine in avail:
            return engine
    raise LookupError(f"no_engine_available for task kind={task.get('kind', 'url')}")


def crawl(task: dict, engines: dict | None = None) -> CrawlResult:
    """Execute one crawl task through the routed engine adapter. Until real
    adapters land, every call ends in an honest failed/blocked result."""
    job = task.get("job_id") or hash_content(f"{task}{time.time()}".encode())[:12]
    url = task.get("url", "")
    try:
        engine = route(task)
    except LookupError as e:
        return CrawlResult(
            job_id=job,
            source_url=url,
            retrieved_at=time.time(),
            engine="none",
            status="failed",
            errors=[str(e)],
        )
    adapter = (engines or {}).get(engine)
    if adapter is None:
        return CrawlResult(
            job_id=job,
            source_url=url,
            retrieved_at=time.time(),
            engine=engine,
            status="failed",
            errors=[f"engine '{engine}' adapter not installed yet (P2 in progress)"],
        )
    return adapter.crawl(task)  # pragma: no cover - real adapters land next
