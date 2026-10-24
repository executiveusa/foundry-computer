"""P2 slice 2: engine adapter contract tests (engines faked via sys.modules)."""

import sys
import types

import pytest

from foundry.crawl import crawl
from foundry.crawl_engines import (
    Crawl4aiAdapter,
    CrawleeAdapter,
    ScraplingAdapter,
    SkyvernAdapter,
    default_engines,
)


class FakeElement:
    def __init__(self, text):
        self._text = text

    def get_all_text(self):
        return self._text


class FakePage:
    def __init__(self, status=200, body=b"<html><h1>Example</h1></html>", mapping=None):
        self.status = status
        self.body = body
        self._mapping = {"h1": [FakeElement("Example Domain")]} if mapping is None else mapping

    def css(self, selector):
        if selector == "boom":
            raise ValueError("bad selector")
        return self._mapping.get(selector, [])


def fake_scrapling(page=None, raises=None):
    mod = types.ModuleType("scrapling")

    class Fetcher:
        @staticmethod
        def get(url, timeout=30):
            if raises:
                raise raises
            return page or FakePage()

    mod.Fetcher = Fetcher
    return mod


@pytest.fixture
def with_scrapling(monkeypatch):
    monkeypatch.setenv("FOUNDRY_CRAWL_ENGINES", "scrapling")
    mod = fake_scrapling()
    monkeypatch.setitem(sys.modules, "scrapling", mod)
    yield mod
    monkeypatch.delitem(sys.modules, "scrapling", raising=False)


def test_available_requires_flag_and_import(monkeypatch):
    monkeypatch.delenv("FOUNDRY_CRAWL_ENGINES", raising=False)
    monkeypatch.setitem(sys.modules, "scrapling", fake_scrapling())
    assert not ScraplingAdapter().available()
    monkeypatch.setenv("FOUNDRY_CRAWL_ENGINES", "scrapling")
    assert ScraplingAdapter().available()
    monkeypatch.delitem(sys.modules, "scrapling")
    assert not ScraplingAdapter().available()


def test_scrapling_success_extracts_schema(with_scrapling):
    r = ScraplingAdapter().crawl({"url": "https://example.com", "schema": {"title": "h1"}})
    assert r.status == "success"
    assert r.extracted_data == {"title": ["Example Domain"]}
    assert len(r.content_hash) == 64
    assert any(e["kind"] == "http_status" for e in r.evidence)


def test_scrapling_blocked_on_403(monkeypatch):
    monkeypatch.setenv("FOUNDRY_CRAWL_ENGINES", "scrapling")
    monkeypatch.setitem(sys.modules, "scrapling", fake_scrapling(page=FakePage(status=403)))
    r = ScraplingAdapter().crawl({"url": "https://x.test", "schema": {"t": "h1"}})
    assert r.status == "blocked"
    assert "http 403" in r.errors


def test_scrapling_network_failure_is_failed_not_success(monkeypatch):
    monkeypatch.setenv("FOUNDRY_CRAWL_ENGINES", "scrapling")
    monkeypatch.setitem(sys.modules, "scrapling", fake_scrapling(raises=TimeoutError("slow")))
    r = ScraplingAdapter().crawl({"url": "https://x.test", "schema": {"t": "h1"}})
    assert r.status == "failed"
    assert "TimeoutError" in r.errors[0]


def test_scrapling_empty_extraction_is_failed(monkeypatch):
    monkeypatch.setenv("FOUNDRY_CRAWL_ENGINES", "scrapling")
    monkeypatch.setitem(sys.modules, "scrapling", fake_scrapling(page=FakePage(mapping={})))
    r = ScraplingAdapter().crawl({"url": "https://x.test", "schema": {"t": "h1"}})
    assert r.status == "failed"
    assert r.extracted_data == {}


def test_scrapling_selector_error_partial_success(with_scrapling):
    r = ScraplingAdapter().crawl(
        {"url": "https://example.com", "schema": {"title": "h1", "bad": "boom"}}
    )
    assert r.status == "success"
    assert r.extracted_data["title"] == ["Example Domain"]
    assert any("bad" in e for e in r.errors)


def test_crawl_end_to_end_via_default_engines(with_scrapling):
    r = crawl({"url": "https://example.com", "schema": {"t": "h1"}}, engines=default_engines())
    assert r.engine == "scrapling"
    assert r.status == "success"


def test_skyvern_unavailable_without_env(monkeypatch):
    monkeypatch.delenv("FOUNDRY_SKYVERN_URL", raising=False)
    monkeypatch.setenv("FOUNDRY_CRAWL_ENGINES", "skyvern")
    assert not SkyvernAdapter().available()


def test_skyvern_posts_task(monkeypatch):
    monkeypatch.setenv("FOUNDRY_CRAWL_ENGINES", "skyvern")
    monkeypatch.setenv("FOUNDRY_SKYVERN_URL", "https://sky.test/")
    import foundry.crawl_engines as ce

    class FakeResp:
        status = 200

        def read(self):
            return b'{"task_id": "abc"}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def fake_urlopen(req, timeout=60):
        seen["url"] = req.full_url
        seen["body"] = req.data
        return FakeResp()

    monkeypatch.setattr(ce.urllib.request, "urlopen", fake_urlopen)
    r = SkyvernAdapter().crawl({"url": "https://x.test", "goal": "click login"})
    assert r.status == "success"
    assert seen["url"] == "https://sky.test/api/v1/tasks"
    assert b"click login" in seen["body"]
    assert r.extracted_data == {"task_id": "abc"}


def test_crawl4ai_and_crawlee_report_installed_state(monkeypatch):
    monkeypatch.setenv("FOUNDRY_CRAWL_ENGINES", "crawl4ai,crawlee")
    # neither is importable in the test env -> unavailable, honestly
    assert not Crawl4aiAdapter().available()
    assert not CrawleeAdapter().available()
    h = Crawl4aiAdapter().health()
    assert h == {"engine": "crawl4ai", "available": False, "installed": False}


def test_default_registry_covers_all_engines():
    assert set(default_engines()) == {"scrapling", "crawl4ai", "crawlee", "skyvern"}
