"""顶层通用小工具：时间戳等跨模块零依赖工具。

约定：以下划线开头的符号视为包内私有，不对外公开 API。
"""

from __future__ import annotations

from datetime import datetime


def _now_iso() -> str:
    """返回当前本地时间的 ISO 格式字符串（秒级精度）。

    跨模块唯一权威实现，verify/dedup/record/recommend/install/plan 等
    需要写「generated_at/installed_at/scanned_at/verified_at」时间戳
    的地方统一从这里 import，避免在每个模块里重复定义。
    """
    return datetime.now().isoformat(timespec="seconds")
