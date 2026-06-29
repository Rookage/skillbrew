"""MCP 市场适配器子包（issue #27 Phase 3 多市场聚合）。

入口：marketplaces.get_adapter(name) → MarketAdapter（smithery / registry）。
新增市场：写一个 adapter 文件 + 在 base.ADAPTERS 登记一行，零改老逻辑。
"""

from __future__ import annotations

from .base import ADAPTERS, DEFAULT_MARKET, MarketAdapter, get_adapter

__all__ = ["ADAPTERS", "DEFAULT_MARKET", "MarketAdapter", "get_adapter"]
