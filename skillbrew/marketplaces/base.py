"""市场适配器抽象层（issue #27 Phase 3 多市场聚合）。

把「搜 MCP / 看详情」抽成统一接口，每个市场实现一个 adapter，挂进注册表按名分发。
Smithery 是第一个实现，官方 MCP Registry 是第二个；新增市场只加文件 + 注册，不改老逻辑。

复用而非重造：
- MarketEntry / ServerDetail / MarketplaceError 仍是 marketplace.py 里的那一套（本模块 import），
  不另起 dataclass，跨市场字段统一映射进同一类型。
- _get_json HTTP 层也复用 marketplace.py 的，adapter 只管「把自家 JSON 映射成 MarketEntry/ServerDetail」。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .registry_official import OfficialRegistryAdapter
from .smithery import SmitheryAdapter


@runtime_checkable
class MarketAdapter(Protocol):
    """市场适配器接口：搜 + 看详情。返回统一的 MarketEntry / ServerDetail。"""

    #: 市场名（CLI --from / --market 用，如 "smithery" / "registry"）
    name: str

    def search(self, query: str, limit: int, page: int) -> list[Any]:
        """搜 MCP，返回 MarketEntry 列表。失败抛 MarketplaceError。"""
        ...

    def info(self, qualified_name: str) -> Any:
        """查单个 MCP 详情，返回 ServerDetail。失败抛 MarketplaceError。"""
        ...


#: 注册表：市场名 → adapter 单例。新增市场在此登记一行。
ADAPTERS: dict[str, MarketAdapter] = {
    "smithery": SmitheryAdapter(),
    "registry": OfficialRegistryAdapter(),
}

#: 默认市场（CLI 不指定 --market 时用这个）。
DEFAULT_MARKET = "smithery"


def get_adapter(market: str | None) -> MarketAdapter:
    """按名取 adapter；None 用默认市场；不认识的市场给友善错。"""
    from skillbrew.marketplace import MarketplaceError

    key = (market or DEFAULT_MARKET).strip().lower()
    adapter = ADAPTERS.get(key)
    if adapter is None:
        known = " / ".join(sorted(ADAPTERS))
        raise MarketplaceError(f"未知市场「{market}」（支持：{known}）")
    return adapter
