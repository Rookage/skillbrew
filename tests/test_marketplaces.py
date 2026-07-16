"""多市场适配器层测试（issue #27 Phase 3：smithery + 官方 registry 聚合）。

分两块：
- get_adapter：分发语义（默认市场、大小写/空白容错、未知市场报错、经 marketplace 包装器路由）。
- OfficialRegistryAdapter：把官方 registry JSON 映射进既有 MarketEntry/ServerDetail
  （search 字段映射、info 取 isLatest、name 含斜杠 URL encode、transport 归一、needs_config）。

隔离：全部 monkeypatch registry_official._get_json，不真联网。
"""

from __future__ import annotations

import pytest

from skillbrew import marketplace
from skillbrew.marketplace import MarketEntry, MarketplaceError, ServerDetail
from skillbrew.marketplaces import ADAPTERS, get_adapter, registry_official


def _fake_json(payload):
    """造一个记录调用 URL 的 _get_json 替身，返回 payload。"""
    seen: list[str] = []

    def _stub(url, timeout=10):
        seen.append(url)
        return payload

    return _stub, seen


# ==================== get_adapter：分发语义 ====================


def test_get_adapter_default_and_case_insensitive():
    """None → 默认 smithery；大小写/首尾空白容错。"""
    assert get_adapter(None).name == "smithery"
    assert get_adapter("smithery").name == "smithery"
    assert get_adapter("Smithery").name == "smithery"
    assert get_adapter(" REGISTRY ").name == "registry"
    assert set(ADAPTERS) == {"smithery", "registry"}


def test_get_adapter_unknown_market_raises():
    """不认识的市场名 → MarketplaceError，消息列已知市场。"""
    with pytest.raises(MarketplaceError) as ei:
        get_adapter("mcp.so")
    msg = str(ei.value)
    assert "未知市场" in msg
    assert "mcp.so" in msg
    assert "smithery" in msg and "registry" in msg


# ==================== OfficialRegistryAdapter：transport 归一 ====================


def test_registry_normalize_transport():
    """streamable-http/http/https → http；sse → sse；空/None/未知 → stdio。"""
    f = registry_official._normalize_transport
    assert f("streamable-http") == "http"
    assert f("streamable_http") == "http"
    assert f("http") == "http"
    assert f("HTTPS") == "http"
    assert f("sse") == "sse"
    assert f("SSE") == "sse"
    assert f("") == "stdio"
    assert f(None) == "stdio"
    assert f("weird") == "stdio"


# ==================== OfficialRegistryAdapter：search 映射 ====================


def test_registry_search_maps_fields(monkeypatch):
    """官方 registry search 结果 → MarketEntry：字段映射 + remote/homepage/use_count=0。"""
    payload = {
        "servers": [
            {
                "server": {
                    "name": "github",
                    "title": "GitHub",
                    "description": "GitHub MCP server",
                    "version": "1.0",
                    "remotes": [{"type": "streamable-http", "url": "https://x/mcp"}],
                    "repository": {"url": "https://github.com/owner/repo"},
                }
            }
        ]
    }
    stub, seen = _fake_json(payload)
    monkeypatch.setattr(registry_official, "_get_json", stub)

    entries = ADAPTERS["registry"].search("github", limit=5, page=1)
    assert len(entries) == 1
    e = entries[0]
    assert isinstance(e, MarketEntry)
    assert e.qualified_name == "github"
    assert e.display_name == "GitHub"
    assert e.description == "GitHub MCP server"
    assert e.use_count == 0  # 官方 registry 不提供人气
    assert e.verified is False
    assert e.remote is True
    assert e.homepage == "https://github.com/owner/repo"
    assert e.score == 0.0
    # URL 含 search + limit 参数
    assert "search=github" in seen[0] and "limit=5" in seen[0]
    assert "/v0/servers" in seen[0]


def test_registry_search_missing_title_and_local(monkeypatch):
    """缺 title → display_name 退回 name；remotes 空 → remote=False。"""
    payload = {
        "servers": [
            {
                "server": {
                    "name": "ac.inference.sh/mcp",
                    "description": "no title here",
                    "remotes": [],
                    "repository": {},
                }
            }
        ]
    }
    stub, _ = _fake_json(payload)
    monkeypatch.setattr(registry_official, "_get_json", stub)

    entries = ADAPTERS["registry"].search("ac", limit=10, page=1)
    e = entries[0]
    assert e.display_name == "ac.inference.sh/mcp"  # 退回 name
    assert e.remote is False
    assert e.homepage == ""


# ==================== OfficialRegistryAdapter：info 映射 ====================


def test_registry_info_picks_latest_and_encodes_slash(monkeypatch):
    """info 取 isLatest 那条 version；name 含斜杠须 URL encode；详情字段映射正确。"""
    payload = {
        "servers": [
            {  # 旧版本：description 不同，不该被选中
                "server": {
                    "name": "ac.inference.sh/mcp",
                    "title": "AC",
                    "description": "OLD version",
                    "remotes": [{"type": "streamable-http", "url": "https://old/mcp"}],
                    "repository": {"url": "https://github.com/o/old"},
                },
                "_meta": {},
            },
            {  # 最新版：isLatest=true，应被选中
                "server": {
                    "name": "ac.inference.sh/mcp",
                    "title": "AC",
                    "description": "NEW version",
                    "remotes": [
                        {
                            "type": "sse",
                            "url": "https://new/mcp",
                            "headers": [{"name": "token", "isRequired": True}],
                        }
                    ],
                    "repository": {"url": "https://github.com/o/new"},
                },
                "_meta": {"io.modelcontextprotocol.registry/official": {"isLatest": True}},
            },
        ]
    }
    stub, seen = _fake_json(payload)
    monkeypatch.setattr(registry_official, "_get_json", stub)

    d = ADAPTERS["registry"].info("ac.inference.sh/mcp")
    assert isinstance(d, ServerDetail)
    assert d.qualified_name == "ac.inference.sh/mcp"
    assert d.display_name == "AC"
    assert d.description == "NEW version"  # 取了 isLatest 那条
    assert d.transport == "sse"  # sse 透传
    assert d.deployment_url == "https://new/mcp"
    assert d.needs_config is True  # headers 有 isRequired=true
    assert d.homepage == "https://github.com/o/new"
    assert d.tool_count == 0  # 官方 registry 不提供
    # name 含斜杠已 URL encode，走 /versions 端点
    assert "ac.inference.sh%2Fmcp" in seen[0]
    assert seen[0].endswith("/versions")


def test_registry_info_falls_back_to_first_when_no_latest(monkeypatch):
    """无 isLatest 标记 → 退回第一条。"""
    payload = {
        "servers": [
            {
                "server": {"name": "x", "title": "X", "description": "first", "remotes": []},
                "_meta": {},
            },
        ]
    }
    stub, _ = _fake_json(payload)
    monkeypatch.setattr(registry_official, "_get_json", stub)

    d = ADAPTERS["registry"].info("x")
    assert d.description == "first"


def test_registry_info_empty_raises(monkeypatch):
    """registry 返回空 servers → MarketplaceError 友善报。"""
    stub, _ = _fake_json({"servers": []})
    monkeypatch.setattr(registry_official, "_get_json", stub)

    with pytest.raises(MarketplaceError) as ei:
        ADAPTERS["registry"].info("ghost")
    assert "查无此 MCP" in str(ei.value)


# ==================== 经 marketplace 包装器的多市场分发 ====================


def test_dispatch_routes_to_registry_and_unknown(monkeypatch):
    """marketplace.search/info 带 market=registry → 走 registry adapter（不碰 smithery）。"""
    payload = {
        "servers": [
            {
                "server": {
                    "name": "github",
                    "title": "GitHub",
                    "description": "via registry",
                    "remotes": [{"type": "streamable-http", "url": "https://r/mcp"}],
                    "repository": {"url": "https://github.com/x/y"},
                }
            }
        ]
    }
    stub, _ = _fake_json(payload)
    monkeypatch.setattr(registry_official, "_get_json", stub)

    entries = marketplace.search("github", market="registry")
    assert entries[0].qualified_name == "github"
    assert entries[0].description == "via registry"  # 确实走了 registry 映射

    # 未知市场经包装器也报错
    with pytest.raises(MarketplaceError):
        marketplace.info("x", market="bogus")
