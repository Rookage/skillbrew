"""skillbrew.schema —— 跨阶段 JSON 产物的轻量类型壳。

给 8 步管线落盘的 7 个跨阶段 JSON 产物套 dataclass + ``SCHEMA_VERSION``，
提供 ``to_dict()`` / ``from_dict()``，形状可校验、前向兼容。纯标准库，零新依赖。

第一版只加新文件、不动老代码、不强制调用；老代码继续直接 ``json.dump``/``json.load``
dict 不受影响。详见 :mod:`skillbrew.schema.models`。
"""

from .models import (
    SCHEMA_VERSION,
    DedupReport,
    InstallList,
    KeyframeAlignItem,
    KeyframeVisionItem,
    PlanData,
    ResolveTrace,
    TranscriptData,
)

__all__ = [
    "SCHEMA_VERSION",
    "TranscriptData",
    "KeyframeAlignItem",
    "KeyframeVisionItem",
    "PlanData",
    "DedupReport",
    "InstallList",
    "ResolveTrace",
]
