"""source adapter 协议 + 注册表。

每个 adapter 代表一种源类型（bilibili/douyin/youtube/webpage/text/...）。
约定：
- detect(src) 是静态类方法，判断这条输入是否归本 adapter 处理。
- fetch(src, out_dir, **kw) 实际下载/抓取，返回对应 FetchResult 数据类。
- ADAPTERS 按「优先级」排序——顺序即匹配顺序。视频源排在文本/网页前；
  text 作为兜底放在最后。

本层只定义协议 + 分发函数；具体实现分文件放在同目录：
- bilibili.py
- douyin.py
- youtube.py
- webpage.py
- text.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Protocol, runtime_checkable


@runtime_checkable
class SourceAdapter(Protocol):
    """单个源类型的适配器。用 ClassVar 声明元信息，实例实现 fetch。"""

    #: 源类型名，用于 data/sources/<subdir> 前缀和 CLI 打印
    name: ClassVar[str]
    #: 匹配顺序（越小越先匹配，0 最先）
    priority: ClassVar[int]
    #: 是否是视频源（需要 ffmpeg/yt-dlp 等外部二进制）
    is_video: ClassVar[bool]
    #: 需要的外部二进制列表（ffmpeg/yt-dlp 等），由调用方负责预检
    required_bins: ClassVar[tuple[str, ...]]

    @classmethod
    def detect(cls, src: str) -> bool:
        """判断 src 是否归本 adapter。src 可能是 URL、ID、本地路径、或裸文本。"""
        ...

    @classmethod
    def resolve_subdir(cls, src: str) -> str:
        """根据 src 算默认子目录名（不含 data/sources/ 前缀）。

        默认用 <name>_<hash 8位十六进制>。各 adapter 可用 ID 覆盖。
        """
        return f"{cls.name}_{hash(src) & 0xFFFFFFFF:08x}"

    def fetch(self, src: str, out_dir: Path, **kwargs: Any) -> Any:
        """执行采集；kwargs 透传源特定参数（如 qn）。返回对应 FetchResult 数据类。"""
        ...


# 注册表：模块 import 时自动 append；顺序决定匹配优先级。
ADAPTERS: list[type[SourceAdapter]] = []


def register(adapter_cls: type[Any]) -> type[Any]:
    """装饰器：把 adapter 类注册到全局注册表。

    注册后按 priority 排序；同 priority 按注册顺序。
    入参类型用 Any：Protocol 类在 @register 装饰点 mypy 不认为是 type[SourceAdapter] 的子类型。
    """
    ADAPTERS.append(adapter_cls)  # type: ignore[arg-type]
    ADAPTERS.sort(key=lambda c: (c.priority, ADAPTERS.index(c) if c in ADAPTERS else 0))
    return adapter_cls


def detect_adapter(src: str) -> type[SourceAdapter] | None:
    """从注册表里找第一个 detect(src) 为真的 adapter；全不匹配返回 None。

    text adapter 默认兜住所有非 URL 输入，所以正常路径一定会命中。
    """
    for a in ADAPTERS:
        if a.detect(src):
            return a
    return None


def source_type(src: str) -> str:
    """返回源类型名（"bilibili"/"douyin"/"youtube"/"webpage"/"text"）。

    检测不到返回 "unknown"。供 CLI 预检和目录命名使用。
    """
    a = detect_adapter(src)
    return a.name if a else "unknown"


def is_video_source(src: str) -> bool:
    """判断 src 是否是视频源（需要 ffmpeg 预检）。"""
    a = detect_adapter(src)
    return bool(a and a.is_video)


def required_bins_for(src: str) -> tuple[str, ...]:
    """返回 src 类型需要的外部二进制列表（空元组表示无需求）。"""
    a = detect_adapter(src)
    return a.required_bins if a else ()


def fetch_with_adapter(src: str, out_dir: Path, **kwargs: Any) -> tuple[Any, type[SourceAdapter]]:
    """自动检测源类型、实例化 adapter、执行 fetch。返回 (result, adapter_class)。

    未匹配时抛 ValueError。
    """
    cls = detect_adapter(src)
    if cls is None:
        raise ValueError(f"无法识别源类型: {src!r}")
    inst = cls()
    result = inst.fetch(src, out_dir, **kwargs)
    return result, cls


def resolve_subdir(src: str) -> str:
    """根据源类型算 data/sources/<subdir> 子目录名；未知类型用 unknown_<hash>。"""
    cls = detect_adapter(src)
    if cls is None:
        return f"unknown_{hash(src) & 0xFFFFFFFF:08x}"
    return cls.resolve_subdir(src)
