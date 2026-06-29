"""官方 MCP Registry 适配器（registry.modelcontextprotocol.io，issue #27 Phase 3）。

官方 registry 是 MCP 协议官方维护的服务器目录，API freeze v0.1，公开只读免 key。
聚合上游市场（含 Smithery 等），是比单一市场更正统的来源。

API 结构（curl 实测，2026-06-30）：
- 搜索：GET /v0/servers?search=<关键词>&limit=<N>&cursor=<游标>
  → {"servers":[{"server":{name,title?,description,version,remotes[{type,url,headers?}],
            repository{url,source?}}],"metadata":{nextCursor,count}}
- 详情：GET /v0/servers/{name}/versions   （name 含斜杠须 URL encode；单条端点 404）
  → 同上结构，含多个 version，取 _meta.official.isLatest=true 那条

字段映射进既有 ServerDetail（不加新 dataclass）：
- remotes[0].type (streamable-http/sse) → transport（归一成 http/sse）
- remotes[0].url → deployment_url
- remotes[0].headers 有 isRequired=true → needs_config
- repository.url → homepage
- 有 remotes → remote=True（官方 registry 几乎都是远程端点）
- tool/prompt/resource_count 官方 search/versions 不提供 → 0（展示层已容错）
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from skillbrew.marketplace import (
    MarketEntry,
    MarketplaceError,
    ServerDetail,
    _get_json,
)

REGISTRY_BASE = "https://registry.modelcontextprotocol.io"

#: streamable-http → http（归一成 add 命令认识的 transport）
_TRANSPORT_MAP = {
    "streamable-http": "http",
    "streamable_http": "http",
    "http": "http",
    "https": "http",
    "sse": "sse",
}


def _normalize_transport(t: str) -> str:
    """官方 registry 的 remotes[].type 归一成 http/sse/stdio。"""
    return _TRANSPORT_MAP.get((t or "").strip().lower(), "stdio")


class OfficialRegistryAdapter:
    """官方 MCP Registry adapter。"""

    name = "registry"

    def search(self, query: str, limit: int, page: int) -> list[Any]:
        qs = urllib.parse.urlencode({"search": query, "limit": limit})
        data = _get_json(f"{REGISTRY_BASE}/v0/servers?{qs}")
        servers = data.get("servers") if isinstance(data, dict) else None
        if not isinstance(servers, list):
            raise MarketplaceError("官方 registry 返回结构异常（缺 servers），可能 API 变更")
        entries: list[MarketEntry] = []
        for item in servers:
            s = item.get("server") if isinstance(item, dict) else None
            if isinstance(s, dict):
                entries.append(self._entry_from_registry(s))
        return entries

    def info(self, qualified_name: str) -> Any:
        name = (qualified_name or "").strip()
        if not name:
            raise MarketplaceError("info 需要一个 MCP 名（如 ac.inference.sh/mcp）")
        # 官方 registry 单条端点 404，详情走 /versions，取 isLatest 那条
        encoded = urllib.parse.quote(name, safe="")
        data = _get_json(f"{REGISTRY_BASE}/v0/servers/{encoded}/versions")
        servers = data.get("servers") if isinstance(data, dict) else None
        if not isinstance(servers, list) or not servers:
            raise MarketplaceError(f"官方 registry 查无此 MCP：{name}")
        latest = self._pick_latest(servers)
        server = latest.get("server") if isinstance(latest, dict) else None
        return self._detail_from_registry(server if isinstance(server, dict) else {})

    # ---------- 映射：registry JSON → 既有 MarketEntry / ServerDetail ----------

    @staticmethod
    def _pick_latest(servers: list[dict]) -> dict:
        """从 /versions 列表取 isLatest=true 的那条；没有则取第一条。"""
        for item in servers:
            meta = (item.get("_meta") or {}) if isinstance(item, dict) else {}
            official = meta.get("io.modelcontextprotocol.registry/official") or {}
            if isinstance(official, dict) and official.get("isLatest"):
                return item
        return servers[0] if servers else {}

    def _entry_from_registry(self, s: dict) -> MarketEntry:
        remotes = s.get("remotes") or []
        repo = s.get("repository") or {}
        name = s.get("name", "") or ""
        title = s.get("title", "") or ""
        return MarketEntry(
            qualified_name=name,
            display_name=title or name,
            description=s.get("description", "") or "",
            use_count=0,  # 官方 registry 不提供人气数
            verified=False,  # 官方 registry 无此字段（用 active 状态判，见详情）
            remote=bool(remotes),
            homepage=repo.get("url", "") or "" if isinstance(repo, dict) else "",
            score=0.0,  # 官方 registry 不返回相关度分数
        )

    def _detail_from_registry(self, s: dict) -> ServerDetail:
        remotes = s.get("remotes") or []
        remote0 = remotes[0] if (remotes and isinstance(remotes[0], dict)) else {}
        headers = remote0.get("headers") if isinstance(remote0, dict) else None
        needs_config = False
        if isinstance(headers, list):
            needs_config = any(
                isinstance(h, dict) and h.get("isRequired") for h in headers
            )
        repo = s.get("repository") or {}
        transport_raw = remote0.get("type", "") if isinstance(remote0, dict) else ""
        return ServerDetail(
            qualified_name=s.get("name", "") or "",
            display_name=s.get("title", "") or s.get("name", "") or "",
            description=s.get("description", "") or "",
            remote=bool(remotes),
            deployment_url=remote0.get("url", "") if isinstance(remote0, dict) else "",
            transport=_normalize_transport(transport_raw),
            tool_count=0,
            prompt_count=0,
            resource_count=0,
            homepage=repo.get("url", "") or "" if isinstance(repo, dict) else "",
            needs_config=needs_config,
        )
