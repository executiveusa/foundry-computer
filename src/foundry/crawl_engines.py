"""Pauli Crawl engine adapters (P2 slice 2).

Each adapter reports availability honestly: feature flag on (FOUNDRY_CRAWL_ENGINES)
AND its engine importable/configured. A crawl that cannot run returns a failed or
blocked CrawlResult; content is never fabricated and a failed extraction is never
marked success.
"""

import json
import time
import urllib.request
from typing import Any

from .crawl import CrawlResult, EngineAdapter, enabled_engines, hash_content


def _installed(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


class HttpEngineAdapter(EngineAdapter):
    """Adds import/configuration probing to the base contract."""

    module: str = ""

    def installed(self) -> bool:
        return bool(self.module) and _installed(self.module)

    def available(self) -> bool:
        return self.name in enabled_engines() and self.installed()

    def health(self) -> dict:
        return {
            "engine": self.name,
            "available": self.available(),
            "installed": self.installed(),
        }

    def _job(self, task: dict) -> str:
        return task.get("job_id") or hash_content(f"{task}{time.time()}".encode())[:12]


class ScraplingAdapter(HttpEngineAdapter):
    """Structured extraction: task = {"url": ..., "schema": {field: css_selector}}."""

    module = "scrapling"

    def __init__(self):
        super().__init__(name="scrapling")

    def crawl(self, task: dict) -> CrawlResult:
        from scrapling import Fetcher

        job = self._job(task)
        url = task.get("url", "")
        started = time.time()
        try:
            page = Fetcher.get(url, timeout=task.get("timeout", 30))
        except Exception as e:  # noqa: BLE001 - engine failures vary; always an honest failed result
            return CrawlResult(
                job_id=job,
                source_url=url,
                retrieved_at=time.time(),
                engine=self.name,
                status="failed",
                errors=[f"{type(e).__name__}: {e}"],
            )
        status = getattr(page, "status", 200) or 200
        body = getattr(page, "body", b"") or b""
        raw = body if isinstance(body, bytes) else str(body).encode()
        evidence = [
            {"kind": "http_status", "value": status},
            {"kind": "elapsed_ms", "value": int((time.time() - started) * 1000)},
        ]
        if status in (401, 403, 429):
            return CrawlResult(
                job_id=job,
                source_url=url,
                retrieved_at=time.time(),
                engine=self.name,
                status="blocked",
                content_hash=hash_content(raw),
                evidence=evidence,
                errors=[f"http {status}"],
            )
        data: dict[str, Any] = {}
        errors: list = []
        for field_name, selector in (task.get("schema") or {}).items():
            try:
                matches = page.css(selector)
                data[field_name] = [self._text(m) for m in matches]
            except Exception as e:  # noqa: BLE001 - selector errors are engine-defined; reported per field
                errors.append(f"{field_name}: {type(e).__name__}: {e}")
        # partial selector failure is still honestly reported; a page fetch that
        # yielded nothing for every field is not a success
        if task.get("schema") and not any(data.get(f) for f in data):
            return CrawlResult(
                job_id=job,
                source_url=url,
                retrieved_at=time.time(),
                engine=self.name,
                status="failed",
                content_hash=hash_content(raw),
                evidence=evidence,
                errors=errors or ["no fields extracted"],
            )
        return CrawlResult(
            job_id=job,
            source_url=url,
            retrieved_at=time.time(),
            engine=self.name,
            status="success",
            content_hash=hash_content(raw),
            extracted_data=data,
            evidence=evidence,
            errors=errors,
        )

    @staticmethod
    def _text(el) -> str:
        for attr in ("get_all_text", "text"):
            v = getattr(el, attr, None)
            if callable(v):
                return str(v())
            if isinstance(v, str):
                return v
        return str(el)


class Crawl4aiAdapter(HttpEngineAdapter):
    """General single-page crawl -> markdown. Default engine."""

    module = "crawl4ai"

    def __init__(self):
        super().__init__(name="crawl4ai")

    def crawl(self, task: dict) -> CrawlResult:
        import asyncio

        from crawl4ai import AsyncWebCrawler

        job = self._job(task)
        url = task.get("url", "")

        async def run():
            async with AsyncWebCrawler() as browser:
                return await browser.arun(url=url)

        try:
            result = asyncio.run(run())
        except Exception as e:  # noqa: BLE001 - engine failures vary; always an honest failed result
            return CrawlResult(
                job_id=job,
                source_url=url,
                retrieved_at=time.time(),
                engine=self.name,
                status="failed",
                errors=[f"{type(e).__name__}: {e}"],
            )
        if not getattr(result, "success", False):
            return CrawlResult(
                job_id=job,
                source_url=url,
                retrieved_at=time.time(),
                engine=self.name,
                status="failed",
                errors=[str(getattr(result, "error_message", "crawl failed"))],
            )
        md = getattr(result, "markdown", "") or ""
        return CrawlResult(
            job_id=job,
            source_url=url,
            retrieved_at=time.time(),
            engine=self.name,
            status="success",
            content_hash=hash_content(md.encode()),
            extracted_data={"markdown": md},
            evidence=[{"kind": "bytes", "value": len(md.encode())}],
        )


class CrawleeAdapter(HttpEngineAdapter):
    """Site/map/batch crawls via Crawlee's BeautifulSoupCrawler."""

    module = "crawlee"

    def __init__(self):
        super().__init__(name="crawlee")

    def crawl(self, task: dict) -> CrawlResult:
        import asyncio

        from crawlee.beautifulsoup_crawler import BeautifulSoupCrawler

        job = self._job(task)
        url = task.get("url", "")
        kind = task.get("kind", "url")
        urls = task.get("urls") or [url]
        max_pages = int(task.get("max_pages", 10))
        found: list[str] = []
        errors: list = []

        async def run():
            crawler = BeautifulSoupCrawler(max_requests_per_crawl=max_pages)

            @crawler.router.default_handler
            async def handler(context) -> None:
                found.append(str(context.request.url))
                if kind in {"site", "map"}:
                    await context.enqueue_links()

            await crawler.run(urls)

        try:
            asyncio.run(run())
        except Exception as e:  # noqa: BLE001 - engine failures vary; always an honest failed result
            return CrawlResult(
                job_id=job,
                source_url=url,
                retrieved_at=time.time(),
                engine=self.name,
                status="failed",
                errors=[f"{type(e).__name__}: {e}"],
            )
        if not found:
            return CrawlResult(
                job_id=job,
                source_url=url,
                retrieved_at=time.time(),
                engine=self.name,
                status="failed",
                errors=errors or ["no pages crawled"],
            )
        blob = "\n".join(found).encode()
        return CrawlResult(
            job_id=job,
            source_url=url,
            retrieved_at=time.time(),
            engine=self.name,
            status="success",
            content_hash=hash_content(blob),
            extracted_data={"kind": kind, "pages": found},
            evidence=[{"kind": "page_count", "value": len(found)}],
        )


class SkyvernAdapter(HttpEngineAdapter):
    """Interactive/browser tasks via a Skyvern service (FOUNDRY_SKYVERN_URL)."""

    def __init__(self):
        super().__init__(name="skyvern")

    def installed(self) -> bool:
        import os

        return bool(os.environ.get("FOUNDRY_SKYVERN_URL"))

    def crawl(self, task: dict) -> CrawlResult:
        import os

        job = self._job(task)
        url = task.get("url", "")
        base = os.environ["FOUNDRY_SKYVERN_URL"].rstrip("/")
        payload = json.dumps({"url": url, "goal": task.get("goal", "")}).encode()
        req = urllib.request.Request(
            f"{base}/api/v1/tasks",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
                status = resp.status
        except OSError as e:
            return CrawlResult(
                job_id=job,
                source_url=url,
                retrieved_at=time.time(),
                engine=self.name,
                status="failed",
                errors=[f"{type(e).__name__}: {e}"],
            )
        data: dict[str, Any] = {}
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = {}  # body kept hashed in evidence either way
        ok = 200 <= status < 300
        return CrawlResult(
            job_id=job,
            source_url=url,
            retrieved_at=time.time(),
            engine=self.name,
            status="success" if ok else "failed",
            content_hash=hash_content(body),
            extracted_data=data,
            evidence=[{"kind": "http_status", "value": status}],
            errors=[] if ok else [f"http {status}"],
        )


def default_engines() -> dict:
    """The real adapter registry. crawl() uses this when none is injected."""
    return {
        a.name: a
        for a in (ScraplingAdapter(), Crawl4aiAdapter(), CrawleeAdapter(), SkyvernAdapter())
    }
