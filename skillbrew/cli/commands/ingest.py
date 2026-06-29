"""`ingest` 子命令：只跑素材采集。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from skillbrew.config import load_config

from ..utils import _format_missing_hint, _require_binaries


def cmd_ingest(args: argparse.Namespace) -> int:
    """只跑采集（下载视频 + 音频 / 抓取网页 / 捕获文本）。"""
    from skillbrew import ingest

    cfg = load_config()
    src = args.source

    # 预检外部二进制（按源类型判断需要啥，网页/纯文本不需要）
    is_video_src = (
        "bilibili.com" in src
        or src.startswith("BV")
        or "douyin.com" in src
        or src.isdigit()
        or "youtube.com" in src
        or "youtu.be" in src
    )
    if is_video_src:
        need = ["ffmpeg"]
        if "douyin.com" in src or src.isdigit() or "youtube.com" in src or "youtu.be" in src:
            need.append("yt-dlp")
        missing = _require_binaries(*need)
        if missing:
            print(_format_missing_hint(missing), file=sys.stderr)
            return 1

    # 自动识别平台
    if "bilibili.com" in src or src.startswith("BV"):
        # B站
        bvid = ingest.parse_bvid(src)
        src_dir = cfg.data_dir / "sources" / bvid
        r = ingest.fetch_bilibili(src, src_dir, qn=args.qn)
        print(f"[OK] {r.title}")
        print(f"     bvid={r.bvid} 时长={r.duration}s")
        print(f"     视频: {r.video_path} ({r.video_path.stat().st_size // 1024}KB)")
        print(f"     音频: {r.audio_path} ({r.audio_path.stat().st_size // 1024}KB)")
    elif "douyin.com" in src or src.isdigit():
        # 抖音：先解析短链拿真实 URL，再提取 video_id
        if "v.douyin.com" in src:
            src = ingest._resolve_short_url(src)
        video_id = ingest.parse_douyin_id(src)
        src_dir = cfg.data_dir / "sources" / f"douyin_{video_id}"
        r = ingest.fetch_douyin(src, src_dir)  # type: ignore[assignment]
        print(f"[OK] {r.title}")
        print(f"     video_id={r.video_id} 时长={r.duration}s")  # type: ignore[attr-defined]
        print(f"     视频: {r.video_path} ({r.video_path.stat().st_size // 1024}KB)")
        print(f"     音频: {r.audio_path} ({r.audio_path.stat().st_size // 1024}KB)")
    elif "youtube.com" in src or "youtu.be" in src:
        # YouTube
        video_id = ingest.parse_youtube_id(src)
        src_dir = cfg.data_dir / "sources" / f"yt_{video_id}"
        r = ingest.fetch_youtube(src, src_dir)  # type: ignore[assignment]
        print(f"[OK] {r.title}")
        print(f"     video_id={r.video_id} 时长={r.duration}s")  # type: ignore[attr-defined]
        print(f"     视频: {r.video_path} ({r.video_path.stat().st_size // 1024}KB)")
        print(f"     音频: {r.audio_path} ({r.audio_path.stat().st_size // 1024}KB)")
        if r.subtitle_path:  # type: ignore[attr-defined]
            print(f"     字幕: {r.subtitle_path}")  # type: ignore[attr-defined]
    elif src.startswith("http://") or src.startswith("https://"):
        # 网页
        src_dir = cfg.data_dir / "sources" / f"web_{hash(src) & 0xFFFFFFFF:08x}"
        r = ingest.fetch_webpage(src, src_dir)  # type: ignore[assignment]
        print(f"[OK] {r.title}")
        print(f"     正文长度: {len(r.text)} 字")  # type: ignore[attr-defined]
        print(f"     输出: {r.text_path}")  # type: ignore[attr-defined]
    elif Path(src).exists() and Path(src).is_file():
        # 本地文件
        src_dir = cfg.data_dir / "sources" / f"file_{Path(src).stem}"
        r = ingest.fetch_text(src, src_dir)  # type: ignore[assignment]
        print(f"[OK] {r.title}")
        print(f"     正文长度: {len(r.text)} 字")  # type: ignore[attr-defined]
        print(f"     输出: {r.text_path}")  # type: ignore[attr-defined]
    else:
        # 当成纯文本输入
        src_dir = cfg.data_dir / "sources" / f"text_{hash(src) & 0xFFFFFFFF:08x}"
        r = ingest.fetch_text(src, src_dir)  # type: ignore[assignment]
        print(f"[OK] {r.title}")
        print(f"     正文长度: {len(r.text)} 字")  # type: ignore[attr-defined]
        print(f"     输出: {r.text_path}")  # type: ignore[attr-defined]
    return 0
