"""B站 adapter。

关键经验（保留注释）：本机对 `www.bilibili.com` 网页层返回 HTTP 412（yt-dlp 也被拦），
但 `api.bilibili.com` 公开 API 全通。故绕开 yt-dlp，直接走公开 API：
① view    `x/web-interface/view?bvid=`        → 元数据(aid/cid/title)
② playurl `x/player/playurl?avid=&cid=&qn=&fnval=16&fourk=1`  ← 非 WBI，免签名
   返回 DASH 流：dash.video[] / dash.audio[]，每条带 baseUrl
③ 选流：视频取 codecs 以 `avc1` 开头里带宽最高者(ffmpeg 可 -c copy 直接重封装)；
        音频取带宽最低者(语音不需要高码率)
④ 下载 video.m4s / audio.m4s（须带 Referer 头）→ ffmpeg 重封装
     video.m4s → video.mp4 (-c copy)
     audio.m4s → audio.mp3 (-vn -c:a libmp3lame -q:a 4)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ._helpers import UA, download, get_json, run, write_json
from .base import register

BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")


@dataclass
class BiliFetchResult:
    """B站获取结果。"""

    bvid: str
    aid: int
    cid: int
    title: str
    duration: int
    pic: str
    video_path: Path
    audio_path: Path
    meta_path: Path


def parse_bvid(s: str) -> str:
    """从完整 URL 或裸 BV 号里提取 BV 号。"""
    m = BVID_RE.search(s)
    if not m:
        raise ValueError(f"未找到 BV 号: {s!r}")
    return m.group(0)


def _headers(bvid: str) -> dict[str, str]:
    return {"User-Agent": UA, "Referer": f"https://www.bilibili.com/video/{bvid}"}


def _pick_streams(dash: dict) -> tuple[dict, dict]:
    """选 1 路视频(avc1 优先、带宽最高) + 1 路音频(带宽最低)。"""
    vids = dash.get("video", [])
    auds = dash.get("audio", [])
    avc = [v for v in vids if str(v.get("codecs", "")).startswith("avc1")]
    vid = max(avc or vids, key=lambda s: s.get("bandwidth", 0))
    aud = min(auds, key=lambda s: s.get("bandwidth", 0)) if auds else {}
    if not vid or not aud:
        raise RuntimeError(f"选流失败：video={len(vids)} audio={len(auds)}")
    return vid, aud


def _stream_url(s: dict) -> str:
    """dash 流地址键名有 baseUrl / base_url 两种，兼容取。"""
    return s.get("baseUrl") or s.get("base_url") or ""


def fetch_bilibili(source: str, out_dir: Path, *, qn: int = 32) -> BiliFetchResult:
    """获取一个 B站视频为 video.mp4 + audio.mp3。

    source: 完整 URL 或裸 BV 号。out_dir: 输出目录（自动建）。
    qn: 请求清晰度(16=360p / 32=480p / 64=720p / 80=1080p)；高码率可能需登录，
        免登录默认 32(480p) 兼顾清晰度与可用性。
    """
    bvid = parse_bvid(source)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    h = _headers(bvid)

    # ① 元数据
    meta = get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", h)
    if meta.get("code") != 0:
        raise RuntimeError(f"view API 错误: {meta.get('message')}")
    info = meta["data"]
    aid, cid = info["aid"], info["cid"]
    write_json(out_dir / "meta.json", info)

    # ② playurl（非 WBI）
    pu = get_json(
        "https://api.bilibili.com/x/player/playurl"
        f"?avid={aid}&cid={cid}&qn={qn}&fnval=16&fnver=0&fourk=1",
        h,
    )
    if pu.get("code") != 0:
        raise RuntimeError(f"playurl API 错误: {pu.get('message')}")
    dash = pu["data"]["dash"]
    write_json(out_dir / "playurl.json", pu["data"])

    # ③ 选流 + ④ 下载
    vid, aud = _pick_streams(dash)
    v_m4s, a_m4s = out_dir / "video.m4s", out_dir / "audio.m4s"
    download(_stream_url(vid), v_m4s, h)
    download(_stream_url(aud), a_m4s, h)

    # 重封装
    video_path, audio_path = out_dir / "video.mp4", out_dir / "audio.mp3"
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(v_m4s),
            "-c",
            "copy",
            str(video_path),
        ]
    )
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(a_m4s),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(audio_path),
        ]
    )

    return BiliFetchResult(
        bvid=bvid,
        aid=aid,
        cid=cid,
        title=info["title"],
        duration=info.get("duration", 0),
        pic=info.get("pic", ""),
        video_path=video_path,
        audio_path=audio_path,
        meta_path=out_dir / "meta.json",
    )


@register
class BilibiliAdapter:
    """B站视频源适配器。"""

    name = "bilibili"
    priority = 10
    is_video = True
    required_bins = ("ffmpeg",)

    @classmethod
    def detect(cls, src: str) -> bool:
        return "bilibili.com" in src or BVID_RE.search(src) is not None

    @classmethod
    def resolve_subdir(cls, src: str) -> str:
        return parse_bvid(src)

    def fetch(self, src: str, out_dir: Path, *, qn: int = 32, **_kw: object) -> BiliFetchResult:
        return fetch_bilibili(src, out_dir, qn=qn)
