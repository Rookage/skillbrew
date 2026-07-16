"""MCP 市场对接层 —— 在 MCP 市场里搜索、预览 MCP 服务器（issue #27 Phase 1）。

当前对接 Smithery（api.smithery.ai），公开查询无需 key。Smithery 是 MCP 生态主流市场，
收录的服务器以「远程托管」为主（remote HTTP，给一个 deploymentUrl 即可连），所以这里的
条目展示的是部署信息而非 npx 本地命令；具体装法由后续 add 命令（Phase 2）按 connection
类型决定，本模块只管搜和看，不安装、不写配置、不调 LLM。

设计要点：
- 纯标准库（urllib），不引第三方依赖。
- HTTP 层抽成单函数 _get_json，便于测试 monkeypatch，不真联网。
- 超时 / 网络 / HTTP 错 / 解析异常统一包成 MarketplaceError，友善报，不抛裸异常。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

SMITHERY_BASE = "https://api.smithery.ai"
DEFAULT_TIMEOUT = 10  # 秒；市场查询超时不崩（issue #27 验收项）
DEFAULT_LIMIT = 10
_UA = "skillbrew-marketplace/1.0 (+https://github.com/Rookage/skillbrew)"


class MarketplaceError(Exception):
    """市场查询失败（超时 / 网络 / HTTP 错 / 解析错误）。"""


def _get_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> Any:
    """GET 一个 URL 返回解析后的 JSON；任何失败统一转 MarketplaceError。"""
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as e:
        raise MarketplaceError(f"市场返回 HTTP {e.code}：{e.reason}") from e
    except urllib.error.URLError as e:
        raise MarketplaceError(f"无法连接市场（{e.reason}），请检查网络") from e
    except TimeoutError as e:
        raise MarketplaceError(f"市场查询超时（>{timeout}s）") from e
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise MarketplaceError("市场返回非 JSON，可能 API 变更") from e


@dataclass(slots=True)
class MarketEntry:
    """搜索结果里的一条 MCP（Smithery server 列表项的展示子集）。

    Smithery 的 search 返回不含安装命令（command/args），只有概览字段；安装信息在
    info 详情端点里（见 ServerDetail）。
    """

    qualified_name: str  # 规范名，info/add 用它定位（如 "github"）
    display_name: str
    description: str
    use_count: int  # 人气（Smithery useCount）
    verified: bool  # Smithery 官方核实
    remote: bool  # 是否远程托管
    homepage: str
    score: float  # 相关度

    @classmethod
    def from_smithery(cls, d: dict[str, Any]) -> MarketEntry:
        return cls(
            qualified_name=d.get("qualifiedName", "") or "",
            display_name=d.get("displayName", "") or "",
            description=d.get("description", "") or "",
            use_count=int(d.get("useCount", 0) or 0),
            verified=bool(d.get("verified", False)),
            remote=bool(d.get("remote", False)),
            homepage=d.get("homepage", "") or "",
            score=float(d.get("score", 0.0) or 0.0),
        )


@dataclass(slots=True)
class ServerDetail:
    """单个 MCP 的详情（Smithery info 端点）。展示用，不含装法决策。"""

    qualified_name: str
    display_name: str
    description: str
    remote: bool
    deployment_url: str  # 远程托管地址（remote=True 时有）
    transport: str  # 连接方式（http/stdio，取自 connections[0].type）
    tool_count: int
    prompt_count: int
    resource_count: int
    homepage: str
    needs_config: bool  # 是否需用户填配置（configSchema 有 properties）

    @classmethod
    def from_smithery(cls, d: dict[str, Any]) -> ServerDetail:
        conns = d.get("connections") or []
        conn = conns[0] if conns and isinstance(conns[0], dict) else {}
        config_schema = conn.get("configSchema") or {}
        props = config_schema.get("properties") if isinstance(config_schema, dict) else None
        return cls(
            qualified_name=d.get("qualifiedName", "") or "",
            display_name=d.get("displayName", "") or "",
            description=d.get("description", "") or "",
            remote=bool(d.get("remote", False)),
            deployment_url=d.get("deploymentUrl", "") or (conn.get("deploymentUrl", "") or ""),
            transport=conn.get("type", "") or "",
            tool_count=len(d.get("tools") or []),
            prompt_count=len(d.get("prompts") or []),
            resource_count=len(d.get("resources") or []),
            homepage=d.get("homepage", "") or "",
            needs_config=bool(props),
        )


def search_smithery(query: str, limit: int = DEFAULT_LIMIT, page: int = 1) -> list[MarketEntry]:
    """在 Smithery 搜 MCP，返回条目列表（默认 10 条/页）。"""
    qs = urllib.parse.urlencode({"q": query, "page": page, "pageSize": limit})
    data = _get_json(f"{SMITHERY_BASE}/servers?{qs}")
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, list):
        raise MarketplaceError("市场返回结构异常（缺 servers 列表），可能 API 变更")
    return [MarketEntry.from_smithery(s) for s in servers if isinstance(s, dict)]


def info_smithery(qualified_name: str) -> ServerDetail:
    """查单个 MCP 详情（按 qualifiedName，如 "github"）—— Smithery 实现。"""
    name = (qualified_name or "").strip().lstrip("@")
    if not name:
        raise MarketplaceError("info 需要一个 MCP 名（如 github）")
    url = f"{SMITHERY_BASE}/servers/{urllib.parse.quote(name)}"
    data = _get_json(url)
    if not isinstance(data, dict):
        raise MarketplaceError("市场详情返回结构异常，可能 API 变更")
    return ServerDetail.from_smithery(data)


def search(
    query: str, limit: int = DEFAULT_LIMIT, page: int = 1, market: str | None = None
) -> list[MarketEntry]:
    """搜 MCP（多市场分发）。不指定 market 走默认（smithery）。

    Phase 3 起支持多市场：通过 marketplaces 适配器层按名分发到 smithery / registry。
    老 CLI 不传 market 时行为与 Phase 1/2 完全一致（仍走 smithery）。
    """
    from skillbrew.marketplaces import get_adapter

    return get_adapter(market).search(query, limit=limit, page=page)


def info(qualified_name: str, market: str | None = None) -> ServerDetail:
    """查单个 MCP 详情（多市场分发）。不指定 market 走默认（smithery）。"""
    from skillbrew.marketplaces import get_adapter

    return get_adapter(market).info(qualified_name)
