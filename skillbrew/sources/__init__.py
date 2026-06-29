"""skillbrew.sources：源类型适配器层。

import 本包即自动注册所有内置 adapter（bilibili/douyin/youtube/webpage/text）。
对外主要符号：
- detect_adapter(src) → 适配器类
- fetch_with_adapter(src, out_dir, **kw) → (result, adapter_cls)
- source_type(src) → "bilibili"/"douyin"/"youtube"/"web"/"text"
- is_video_source(src) → bool
- required_bins_for(src) → tuple[str,...]
- resolve_subdir(src) → str（data/sources 下的子目录名）

每个子模块还导出原 fetch 函数和结果数据类，供需要精细控制的调用方直接用。
"""

from __future__ import annotations

# 按 priority 顺序 import，触发 @register 装饰器注册。
# 顺序：bilibili(10) → douyin(20) → youtube(30) → webpage(50) → text(100)
from . import bilibili as _bilibili  # noqa: F401
from . import douyin as _douyin  # noqa: F401
from . import text as _text  # noqa: F401
from . import webpage as _webpage  # noqa: F401
from . import youtube as _youtube  # noqa: F401
from ._helpers import resolve_short_url  # noqa: E402  (旧路径 ingest._resolve_short_url)
from .base import (  # noqa: E402
    ADAPTERS,
    SourceAdapter,
    detect_adapter,
    fetch_with_adapter,
    is_video_source,
    register,
    required_bins_for,
    resolve_subdir,
    source_type,
)

# 数据类 + fetch 函数 re-export（供外部直接用，保持旧 import 路径可迁移）
from .bilibili import BVID_RE, BiliFetchResult, fetch_bilibili, parse_bvid  # noqa: E402
from .douyin import DOUYIN_ID_RE, DouyinFetchResult, fetch_douyin, parse_douyin_id  # noqa: E402
from .text import TextFetchResult, fetch_text  # noqa: E402
from .webpage import fetch_webpage  # noqa: E402
from .youtube import YOUTUBE_RE, YoutubeFetchResult, fetch_youtube, parse_youtube_id  # noqa: E402

__all__ = [
    # 协议/注册表/分发
    "ADAPTERS",
    "SourceAdapter",
    "detect_adapter",
    "fetch_with_adapter",
    "is_video_source",
    "register",
    "required_bins_for",
    "resolve_subdir",
    "source_type",
    # 结果数据类
    "BiliFetchResult",
    "DouyinFetchResult",
    "TextFetchResult",
    "YoutubeFetchResult",
    # fetch 函数
    "fetch_bilibili",
    "fetch_douyin",
    "fetch_youtube",
    "fetch_webpage",
    "fetch_text",
    # 解析工具
    "BVID_RE",
    "DOUYIN_ID_RE",
    "YOUTUBE_RE",
    "parse_bvid",
    "parse_douyin_id",
    "parse_youtube_id",
    "resolve_short_url",
]
