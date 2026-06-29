"""marketplace 对接层测试 —— monkeypatch _get_json 模拟 HTTP，不真联网。"""

from __future__ import annotations

import urllib.error

import pytest

from skillbrew import marketplace
from skillbrew.marketplace import MarketEntry, MarketplaceError, ServerDetail

SEARCH_PAYLOAD = {
    "servers": [
        {
            "qualifiedName": "github",
            "displayName": "GitHub",
            "description": "Connect AI agents to GitHub",
            "useCount": 3454,
            "verified": True,
            "remote": True,
            "homepage": "https://github.com/",
            "score": 0.05,
        },
        {
            "qualifiedName": "sqlite",
            "displayName": "SQLite",
            "description": "Query SQLite databases",
            "useCount": 100,
            "verified": False,
            "remote": False,
            "homepage": "",
            "score": 0.02,
        },
    ],
    "pagination": {"currentPage": 1, "pageSize": 2, "totalPages": 1, "totalCount": 2},
}

INFO_PAYLOAD = {
    "qualifiedName": "github",
    "displayName": "GitHub",
    "description": "Connect your AI agents to GitHub",
    "remote": True,
    "deploymentUrl": "https://github.run.tools",
    "homepage": "https://github.com/",
    "connections": [
        {
            "type": "http",
            "deploymentUrl": "https://github.run.tools",
            "configSchema": {"properties": {"token": {}}},
        }
    ],
    "tools": [{"name": "t1"}, {"name": "t2"}, {"name": "t3"}],
    "resources": [],
    "prompts": [{"name": "p1"}],
}


def test_search_parses_entries(monkeypatch):
    captured = {}

    def fake_get(url, timeout=10):
        captured["url"] = url
        return SEARCH_PAYLOAD

    monkeypatch.setattr(marketplace, "_get_json", fake_get)
    entries = marketplace.search("github", limit=5, page=2)

    assert len(entries) == 2
    assert isinstance(entries[0], MarketEntry)
    assert entries[0].qualified_name == "github"
    assert entries[0].use_count == 3454
    assert entries[0].verified is True
    assert entries[0].remote is True
    assert entries[1].verified is False
    # limit / page 透传到查询参数
    assert "pageSize=5" in captured["url"]
    assert "page=2" in captured["url"]


def test_search_empty_servers(monkeypatch):
    monkeypatch.setattr(marketplace, "_get_json", lambda url, timeout=10: {"servers": []})
    assert marketplace.search("nope") == []


def test_search_bad_structure(monkeypatch):
    monkeypatch.setattr(marketplace, "_get_json", lambda url, timeout=10: {"unexpected": 1})
    with pytest.raises(MarketplaceError):
        marketplace.search("x")


def test_search_propagates_marketplace_error(monkeypatch):
    def boom(url, timeout=10):
        raise MarketplaceError("市场查询超时（>10s）")

    monkeypatch.setattr(marketplace, "_get_json", boom)
    with pytest.raises(MarketplaceError):
        marketplace.search("x")


def test_info_parses_detail(monkeypatch):
    captured = {}

    def fake_get(url, timeout=10):
        captured["url"] = url
        return INFO_PAYLOAD

    monkeypatch.setattr(marketplace, "_get_json", fake_get)
    d = marketplace.info("github")

    assert isinstance(d, ServerDetail)
    assert d.qualified_name == "github"
    assert d.remote is True
    assert d.deployment_url == "https://github.run.tools"
    assert d.transport == "http"
    assert d.tool_count == 3
    assert d.prompt_count == 1
    assert d.resource_count == 0
    assert d.needs_config is True
    assert "/servers/github" in captured["url"]


def test_info_strips_at_prefix(monkeypatch):
    captured = {}

    def fake_get(url, timeout=10):
        captured["url"] = url
        return INFO_PAYLOAD

    monkeypatch.setattr(marketplace, "_get_json", fake_get)
    marketplace.info("@github")
    assert "/servers/github" in captured["url"]


def test_info_rejects_empty_name():
    with pytest.raises(MarketplaceError):
        marketplace.info("")


def test_get_json_wraps_http_error(monkeypatch):
    def boom(url, timeout=10):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    monkeypatch.setattr(marketplace.urllib.request, "urlopen", boom)
    with pytest.raises(MarketplaceError):
        marketplace._get_json("https://api.smithery.ai/servers/nope")
