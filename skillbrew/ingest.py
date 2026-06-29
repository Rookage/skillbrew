"""ingest：素材采集入口（薄壳 + 兼容 re-export）。

从 P3-1 起，具体 fetch 逻辑已拆分到 `skillbrew.sources` 子包：
- sources/bilibili.py  → B站
- sources/douyin.py    → 抖音
- sources/youtube.py   → YouTube（修复了 _main() 漏 dispatch 的 bug）
- sources/webpage.py   → 网页
- sources/text.py      → 纯文本/本地文件
- sources/base.py      → SourceAdapter Protocol + 注册表 + 分发函数

本文件保留：
1. 对所有旧路径符号的 re-export（`from skillbrew import ingest; ingest.fetch_bilibili` 等继续可用）。
2. `python -m skillbrew.ingest <src>` 直接入口（已改用 sources 注册表，补上了 YouTube 分支）。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 触发 adapter 注册；统一从 sources 包 re-export 保持旧代码 import 路径不破坏。
from skillbrew.sources import (  # noqa: F401  (re-export)
    ADAPTERS,
    BVID_RE,
    DOUYIN_ID_RE,
    YOUTUBE_RE,
    BiliFetchResult,
    DouyinFetchResult,
    SourceAdapter,
    TextFetchResult,
    YoutubeFetchResult,
    detect_adapter,
    fetch_bilibili,
    fetch_douyin,
    fetch_text,
    fetch_webpage,
    fetch_with_adapter,
    fetch_youtube,
    is_video_source,
    parse_bvid,
    parse_douyin_id,
    parse_youtube_id,
    required_bins_for,
    resolve_short_url,
    resolve_subdir,
    source_type,
)


def _print_video_result(r: object) -> None:
    """打印视频类型 FetchResult 的摘要。bilibili/douyin/youtube 通用。"""
    title = getattr(r, "title", "")
    vpath: Path = getattr(r, "video_path")
    apath: Path = getattr(r, "audio_path")
    print(f"[OK] {title}")
    # 源特定字段
    for field in ("bvid", "video_id"):
        v = getattr(r, field, None)
        if v is not None:
            print(f"     {field}={v}", end="")
    dur = getattr(r, "duration", 0) or 0
    if dur:
        print(f" 时长={dur}s")
    else:
        print()
    print(f"     视频: {vpath} ({vpath.stat().st_size // 1024}KB)")
    print(f"     音频: {apath} ({apath.stat().st_size // 1024}KB)")
    spath = getattr(r, "subtitle_path", None)
    if spath:
        print(f"     字幕: {spath}")


def _print_text_result(r: object) -> None:
    """打印文本类型 FetchResult 的摘要。"""
    title = getattr(r, "title", "")
    text: str = getattr(r, "text", "")
    tpath: Path = getattr(r, "text_path")
    print(f"[OK] {title}")
    print(f"     正文长度: {len(text)} 字")
    print(f"     输出: {tpath}")


def _main() -> int:
    if len(sys.argv) < 2:
        print(
            "用法: python -m skillbrew.ingest "
            "<B站URL/BV号|抖音URL/ID|YouTube URL|网页URL|文本/文件> [输出目录]"
        )
        return 1
    src = sys.argv[1]

    out_root = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    # 短链解析（仅抖音；其他源 base.resolve_subdir 已能直接给 ID）
    resolved_src = src
    if "v.douyin.com" in src or (src.isdigit() and not src.startswith("http")):
        if not src.startswith("http"):
            resolved_src = f"https://v.douyin.com/{src}/"
        try:
            resolved_src = resolve_short_url(resolved_src)
        except Exception:
            resolved_src = src  # 解析失败就原样交给 adapter（fetch 里会再试）

    cls = detect_adapter(src)
    if cls is None:
        print(f"[FAIL] 无法识别源类型: {src!r}", file=sys.stderr)
        return 2

    if out_root is None:
        # douyin 短链场景：先 resolve 再算子目录名，避免目录名里带 "unknown"
        subdir_src = resolved_src if cls.name == "douyin" else src
        out_root = Path("data/sources") / cls.resolve_subdir(subdir_src)

    r, _ = fetch_with_adapter(src, out_root)

    if cls.is_video:
        _print_video_result(r)
    else:
        _print_text_result(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
