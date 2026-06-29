"""Smithery 市场适配器（包装 marketplace.py 现有逻辑，零重写）。

Smithery 是 Phase 1 已对接的市场，逻辑全在 marketplace.py 里（search/info + from_smithery）。
本 adapter 只是把那套包成统一接口，不重写、不复制。
"""

from __future__ import annotations

from typing import Any

from skillbrew import marketplace as _mp


class SmitheryAdapter:
    """Smithery adapter：直接复用 marketplace.py 的 search/info。"""

    name = "smithery"

    def search(self, query: str, limit: int, page: int) -> list[Any]:
        return _mp.search_smithery(query, limit=limit, page=page)

    def info(self, qualified_name: str) -> Any:
        return _mp.info_smithery(qualified_name)
