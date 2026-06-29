"""`ingest` 子命令：只跑素材采集（多源版，P3-1）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 注意：通过 skillbrew.ingest 模块间接引用 fetch_*，这样测试 monkeypatch
# `skillbrew.ingest.fetch_webpage` / `fetch_bilibili` / `fetch_douyin` 时能生效
# （旧测试路径必须保留——P3-1 零测试改动原则）。
from skillbrew import ingest
from skillbrew.config import load_config
from skillbrew.sources import (
    detect_adapter,
    is_video_source,
    required_bins_for,
    resolve_subdir,
    source_type,
)

from ..utils import _format_missing_hint, _require_binaries

_FETCH_FN_BY_NAME = {
    "bilibili": "fetch_bilibili",
    "douyin": "fetch_douyin",
    "youtube": "fetch_youtube",
    "web": "fetch_webpage",
    "text": "fetch_text",
}


def _print_video(r: object, stype: str) -> None:
    title = getattr(r, "title", "")
    vpath: Path = getattr(r, "video_path")
    apath: Path = getattr(r, "audio_path")
    print(f"[OK] {title}")
    if stype == "bilibili":
        print(f"     bvid={getattr(r, 'bvid', '')} 时长={getattr(r, 'duration', 0)}s")
    else:
        vid = getattr(r, "video_id", "")
        print(f"     video_id={vid} 时长={getattr(r, 'duration', 0)}s")
    try:
        vsize = vpath.stat().st_size // 1024
        asize = apath.stat().st_size // 1024
    except OSError:
        vsize = asize = 0
    print(f"     视频: {vpath} ({vsize}KB)")
    print(f"     音频: {apath} ({asize}KB)")
    sp = getattr(r, "subtitle_path", None)
    if sp:
        print(f"     字幕: {sp}")


def _print_text(r: object) -> None:
    title = getattr(r, "title", "")
    text = getattr(r, "text", "")
    tpath = getattr(r, "text_path", "")
    print(f"[OK] {title}")
    print(f"     正文长度: {len(text)} 字")
    print(f"     输出: {tpath}")


def cmd_ingest(args: argparse.Namespace) -> int:
    """只跑采集（下载视频 + 音频 / 抓取网页 / 捕获文本）。"""
    cfg = load_config()
    src = args.source

    # 预检：需要哪些外部二进制（通过 sources 注册表统一判断）
    need = list(required_bins_for(src))
    if need:
        missing = _require_binaries(*need)
        if missing:
            print(_format_missing_hint(missing), file=sys.stderr)
            return 1

    # 识别适配器
    cls = detect_adapter(src)
    if cls is None:
        print(f"[FAIL] 无法识别源类型: {src!r}", file=sys.stderr)
        return 2
    stype = source_type(src)
    video = is_video_source(src)

    # 输出目录：data/sources/<subdir>
    src_dir = cfg.data_dir / "sources" / resolve_subdir(src)
    src_dir.mkdir(parents=True, exist_ok=True)

    # 取 fetch 函数——关键：通过 skillbrew.ingest 模块属性取，
    # 以便测试 monkeypatch "skillbrew.ingest.fetch_webpage" 生效。
    fn_name = _FETCH_FN_BY_NAME[stype]
    fetch_fn = getattr(ingest, fn_name)

    kwargs: dict = {}
    if stype == "bilibili":
        kwargs["qn"] = args.qn

    r = fetch_fn(src, src_dir, **kwargs)
    if video:
        _print_video(r, stype)
    else:
        _print_text(r)
    return 0
