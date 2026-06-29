"""抖音 adapter。使用 yt-dlp 提取（抖音 API 需要复杂签名，yt-dlp 已处理）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ._helpers import read_json, resolve_short_url, run, write_json
from .base import register

DOUYIN_ID_RE = re.compile(r"/video/(\d+)")


@dataclass
class DouyinFetchResult:
    """抖音获取结果。"""

    video_id: str
    title: str
    duration: int
    video_path: Path
    audio_path: Path
    meta_path: Path


def parse_douyin_id(s: str) -> str:
    """从完整 URL 或裸 ID 里提取抖音视频 ID。"""
    m = DOUYIN_ID_RE.search(s)
    if m:
        return m.group(1)
    if s.isdigit():
        return s
    raise ValueError(f"未找到抖音视频 ID: {s!r}")


def fetch_douyin(source: str, out_dir: Path) -> DouyinFetchResult:
    """获取一个抖音视频为 video.mp4 + audio.mp3。

    source: 完整 URL、短链或裸视频 ID。out_dir: 输出目录（自动建）。
    使用 yt-dlp 提取（抖音 API 需要复杂签名，yt-dlp 已处理）。
    """
    # 解析短链
    if "v.douyin.com" in source or source.isdigit():
        if not source.startswith("http"):
            source = f"https://v.douyin.com/{source}/"
        source = resolve_short_url(source)

    video_id = parse_douyin_id(source)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 用 yt-dlp 下载视频（抖音格式是音视频合一的 mp4）
    video_tmp = out_dir / "video_tmp.mp4"
    run(
        [
            "yt-dlp",
            "-f",
            "best[ext=mp4]/best",
            "-o",
            str(video_tmp),
            "--write-info-json",
            "--no-playlist",
            source,
        ]
    )

    # 重命名视频
    video_path = out_dir / "video.mp4"
    video_tmp.rename(video_path)

    # 用 ffmpeg 从视频提取音频
    audio_path = out_dir / "audio.mp3"
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video_path),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(audio_path),
        ]
    )

    # 读取 yt-dlp 的 info.json
    info_json = out_dir / "video_tmp.info.json"
    if info_json.exists():
        info_json.rename(out_dir / "meta.json")
    else:
        meta = {"id": video_id, "url": source, "title": f"抖音视频 {video_id}"}
        write_json(out_dir / "meta.json", meta)

    meta = read_json(out_dir / "meta.json")
    title = meta.get("title", f"抖音视频 {video_id}")
    duration = int(meta.get("duration", 0) or 0)

    return DouyinFetchResult(
        video_id=video_id,
        title=title,
        duration=duration,
        video_path=video_path,
        audio_path=audio_path,
        meta_path=out_dir / "meta.json",
    )


@register
class DouyinAdapter:
    """抖音视频源适配器。"""

    name = "douyin"
    priority = 20
    is_video = True
    required_bins = ("ffmpeg", "yt-dlp")

    @classmethod
    def detect(cls, src: str) -> bool:
        if "douyin.com" in src:
            return True
        if src.isdigit():
            # 纯数字可能是抖音 ID；注意 BVID_RE 不会把纯数字当 B 站 ID
            return True
        return False

    @classmethod
    def resolve_subdir(cls, src: str) -> str:
        # 短链场景先解出真实 URL 取 ID 可能失败；这里直接 parse
        try:
            vid = parse_douyin_id(src)
        except ValueError:
            vid = "unknown"
        return f"douyin_{vid}"

    def fetch(self, src: str, out_dir: Path, **_kw: object) -> DouyinFetchResult:
        return fetch_douyin(src, out_dir)
