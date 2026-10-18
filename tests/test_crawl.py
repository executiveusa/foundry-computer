"""Pauli Crawl router + contract: no network, stub engines only."""

import pytest

from foundry.crawl import CrawlResult, crawl, enabled_engines, hash_content, route


def test_default_routes_to_crawl4ai():
    assert route({"url": "https://x.com"}, available={"crawl4ai"}) == "crawl4ai"


def test_schema_extraction_routes_to_scrapling():
    assert (
        route({"url": "u", "schema": {"a": "str"}}, available={"scrapling", "crawl4ai"})
        == "scrapling"
    )


def test_site_crawl_routes_to_crawlee():
    assert route({"kind": "site", "url": "u"}, available={"crawlee", "crawl4ai"}) == "crawlee"


def test_interactive_routes_to_skyvern():
    assert route({"url": "u", "interactive": True}, available={"skyvern", "crawl4ai"}) == "skyvern"


def test_preferred_engine_missing_falls_back():
    assert route({"url": "u", "schema": {}}, available={"crawl4ai"}) == "crawl4ai"


def test_nothing_available_raises():
    with pytest.raises(LookupError, match="no_engine_available"):
        route({"url": "u"}, available=set())


def test_flags_from_env(monkeypatch):
    monkeypatch.setenv("FOUNDRY_CRAWL_ENGINES", "crawl4ai, crawlee")
    assert enabled_engines() == {"crawl4ai", "crawlee"}
    monkeypatch.delenv("FOUNDRY_CRAWL_ENGINES")
    assert enabled_engines() == set()


def test_crawl_without_engines_is_honest_failure(monkeypatch):
    monkeypatch.delenv("FOUNDRY_CRAWL_ENGINES", raising=False)
    r = crawl({"url": "https://example.com"})
    assert r.status == "failed"
    assert "no_engine_available" in r.errors[0]
    assert r.extracted_data == {}  # nothing fabricated


def test_crawl_with_flag_but_no_adapter_is_honest(monkeypatch):
    monkeypatch.setenv("FOUNDRY_CRAWL_ENGINES", "crawl4ai")
    r = crawl({"url": "https://example.com"})
    assert r.status == "failed"
    assert "not installed yet" in r.errors[0]
    assert r.engine == "crawl4ai"


def test_result_schema_shape():
    r = CrawlResult(
        job_id="j1",
        source_url="u",
        retrieved_at=1.0,
        engine="crawl4ai",
        status="success",
        content_hash=hash_content(b"abc"),
    )
    d = r.to_dict()
    assert d["schema_version"] == 1
    assert d["content_hash"] == hash_content(b"abc")
    assert set(d) >= {
        "job_id",
        "source_url",
        "retrieved_at",
        "engine",
        "status",
        "content_hash",
        "extracted_data",
        "evidence",
        "errors",
    }
