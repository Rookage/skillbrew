"""YouTube adapter：yt-dlp 下载视频 + 自动字幕。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ._helpers import read_json, run, write_json
from .base import register

YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


@dataclass
class YoutubeFetchResult:
    """YouTube 获取结果。"""

    video_id: str
    title: str
    duration: int
    video_path: Path
    audio_path: Path
    subtitle_path: Path | None  # 自动字幕 .vtt，无字幕时为 None
    meta_path: Path


def parse_youtube_id(s: str) -> str:
    """从完整 URL 里提取 YouTube 视频 ID（11 位字母数字_-）。"""
    m = YOUTUBE_RE.search(s)
    if not m:
        raise ValueError(f"未找到 YouTube 视频 ID: {s!r}")
    return m.group(1)


def _yt_dlp_run(out_dir: Path, extra_args: list[str], source: str) -> Path:
    """跑 yt-dlp，返回视频输出路径。"""
    video_tmp = out_dir / "video_tmp.mp4"
    cmd = (
        [
            "yt-dlp",
            "-f",
            "best[ext=mp4]/best",
            "-o",
            str(video_tmp),
            "--write-info-json",
            "--no-playlist",
        ]
        + extra_args
        + [source]
    )
    run(cmd)
    return video_tmp


def _find_subtitle(out_dir: Path) -> Path | None:
    """找 yt-dlp 下载的自动字幕 .vtt 文件（优先级：zh-Hans > zh > en > 任意 .vtt）。"""
    for lang in ("zh-Hans", "zh", "en"):
        candidate = out_dir / f"video_tmp.{lang}.vtt"
        if candidate.exists():
            return candidate
    vtt_files = list(out_dir.glob("*.vtt"))
    return vtt_files[0] if vtt_files else None


def fetch_youtube(source: str, out_dir: Path) -> YoutubeFetchResult:
    """获取一个 YouTube 视频为 video.mp4 + audio.mp3 + 自动字幕 (.vtt)。

    source: 完整 URL（youtube.com/watch?v=... 或 youtu.be/...）。
    out_dir: 输出目录（自动建）。
    自动提取 zh-Hans/zh-Hant/zh/en 字幕（若可用）。
    """
    video_id = parse_youtube_id(source)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ① 下载视频 + 自动字幕 + info.json
    video_tmp = _yt_dlp_run(
        out_dir,
        [
            "--write-auto-subs",
            "--sub-langs",
            "zh-Hans,zh-Hant,zh,en",
            "--convert-subs",
            "vtt",
        ],
        source,
    )

    # ② 重命名视频
    video_path = out_dir / "video.mp4"
    video_tmp.rename(video_path)

    # ③ 用 ffmpeg 从视频提取音频
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

    # ④ 找自动字幕文件
    subtitle_path = _find_subtitle(out_dir)

    # ⑤ 读取 info.json → meta.json
    info_json = out_dir / "video_tmp.info.json"
    if info_json.exists():
        info_json.rename(out_dir / "meta.json")
    else:
        meta = {"id": video_id, "url": source, "title": f"YouTube 视频 {video_id}"}
        write_json(out_dir / "meta.json", meta)

    meta = read_json(out_dir / "meta.json")
    title = meta.get("title", f"YouTube 视频 {video_id}")
    duration = int(meta.get("duration", 0) or 0)

    return YoutubeFetchResult(
        video_id=video_id,
        title=title,
        duration=duration,
        video_path=video_path,
        audio_path=audio_path,
        subtitle_path=subtitle_path,
        meta_path=out_dir / "meta.json",
    )


@register
class YoutubeAdapter:
    """YouTube 视频源适配器。"""

    name = "youtube"
    priority = 30
    is_video = True
    required_bins = ("ffmpeg", "yt-dlp")

    @classmethod
    def detect(cls, src: str) -> bool:
        return "youtube.com" in src or "youtu.be" in src

    @classmethod
    def resolve_subdir(cls, src: str) -> str:
        return f"yt_{parse_youtube_id(src)}"

    def fetch(self, src: str, out_dir: Path, **_kw: object) -> YoutubeFetchResult:
        return fetch_youtube(src, out_dir)
