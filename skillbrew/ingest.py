"""ingest：采集 + 获取（各源 adapter）。

当前实现：
- B站 adapter：**关键经验**：本机对 `www.bilibili.com` 网页层返回 HTTP 412（yt-dlp 也被拦），
  但 `api.bilibili.com` 公开 API 全通。故绕开 yt-dlp，直接走公开 API：
  ① view    `x/web-interface/view?bvid=`        → 元数据(aid/cid/title)
  ② playurl `x/player/playurl?avid=&cid=&qn=&fnval=16&fourk=1`  ← **非 WBI**，免签名
     返回 DASH 流：dash.video[] / dash.audio[]，每条带 baseUrl
  ③ 选流：视频取 codecs 以 `avc1` 开头里带宽最高者(ffmpeg 可 -c copy 直接重封装)；
          音频取带宽最低者(语音不需要高码率)
  ④ 下载 video.m4s / audio.m4s（须带 Referer 头）→ ffmpeg 重封装
       video.m4s → video.mp4 (-c copy)
       audio.m4s → audio.mp3 (-vn -c:a libmp3lame -q:a 4)

- 抖音 adapter：使用 yt-dlp 提取（抖音 API 需要复杂签名，yt-dlp 已处理）。
  抖音短链需先解析重定向拿真实 URL。

- 网页 adapter（D24）：fetch_webpage — 抓取网页正文，写入 transcript.txt
- 纯文本 adapter（D24）：fetch_text — 裸文本/文档直接写入 transcript.txt
- YouTube adapter：fetch_youtube — yt-dlp 下载视频 + 自动字幕

换源(YouTube/其他)只需新增 adapter，主流程不变。
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")
DOUYIN_ID_RE = re.compile(r"/video/(\d+)")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


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


@dataclass
class DouyinFetchResult:
    """抖音获取结果。"""

    video_id: str
    title: str
    duration: int
    video_path: Path
    audio_path: Path
    meta_path: Path


@dataclass
class TextFetchResult:
    """文本/网页/文档获取结果（视频无关源）。"""

    title: str
    text: str
    text_path: Path
    meta_path: Path


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


def parse_bvid(s: str) -> str:
    """从完整 URL 或裸 BV 号里提取 BV 号。"""
    m = BVID_RE.search(s)
    if not m:
        raise ValueError(f"未找到 BV 号: {s!r}")
    return m.group(0)


def _headers(bvid: str) -> dict[str, str]:
    return {"User-Agent": UA, "Referer": f"https://www.bilibili.com/video/{bvid}"}


def _get_json(url: str, headers: dict[str, str], timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _download(url: str, dest: Path, headers: dict[str, str], timeout: float = 120.0) -> None:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


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


def _run(cmd: list[str]) -> None:
    """跑 ffmpeg，失败抛带 stderr 的错。"""
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {' '.join(cmd)}\n{p.stderr[-800:]}")


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
    meta = _get_json(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}", h)
    if meta.get("code") != 0:
        raise RuntimeError(f"view API 错误: {meta.get('message')}")
    info = meta["data"]
    aid, cid = info["aid"], info["cid"]
    (out_dir / "meta.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ② playurl（非 WBI）
    pu = _get_json(
        "https://api.bilibili.com/x/player/playurl"
        f"?avid={aid}&cid={cid}&qn={qn}&fnval=16&fnver=0&fourk=1",
        h,
    )
    if pu.get("code") != 0:
        raise RuntimeError(f"playurl API 错误: {pu.get('message')}")
    dash = pu["data"]["dash"]
    (out_dir / "playurl.json").write_text(
        json.dumps(pu["data"], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ③ 选流 + ④ 下载
    vid, aud = _pick_streams(dash)
    v_m4s, a_m4s = out_dir / "video.m4s", out_dir / "audio.m4s"
    _download(_stream_url(vid), v_m4s, h)
    _download(_stream_url(aud), a_m4s, h)

    # 重封装
    video_path, audio_path = out_dir / "video.mp4", out_dir / "audio.mp3"
    _run(
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
    _run(
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


def parse_douyin_id(s: str) -> str:
    """从完整 URL 或裸 ID 里提取抖音视频 ID。"""
    # 先尝试正则匹配 /video/1234567890
    m = DOUYIN_ID_RE.search(s)
    if m:
        return m.group(1)
    # 如果是纯数字，直接返回
    if s.isdigit():
        return s
    raise ValueError(f"未找到抖音视频 ID: {s!r}")


def _resolve_short_url(url: str) -> str:
    """解析短链重定向，拿真实 URL。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.url
    except Exception:
        # 如果 HEAD 失败，尝试 GET
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.url


def fetch_douyin(source: str, out_dir: Path) -> DouyinFetchResult:
    """获取一个抖音视频为 video.mp4 + audio.mp3。

    source: 完整 URL、短链或裸视频 ID。out_dir: 输出目录（自动建）。
    使用 yt-dlp 提取（抖音 API 需要复杂签名，yt-dlp 已处理）。
    """
    # 解析短链
    if "v.douyin.com" in source or source.isdigit():
        if not source.startswith("http"):
            source = f"https://v.douyin.com/{source}/"
        source = _resolve_short_url(source)

    video_id = parse_douyin_id(source)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 用 yt-dlp 下载视频（抖音格式是音视频合一的 mp4）
    video_tmp = out_dir / "video_tmp.mp4"

    # 下载视频（含音频，抖音格式是合一的）+ 写 info.json
    _run(
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
    _run(
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

    # 读取 yt-dlp 的 info.json（文件名跟输出模板：video_tmp.info.json）
    info_json = out_dir / "video_tmp.info.json"
    if info_json.exists():
        info_json.rename(out_dir / "meta.json")
    else:
        # 兜底：手动写基本元数据
        meta = {"id": video_id, "url": source, "title": f"抖音视频 {video_id}"}
        (out_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 读取元数据拿标题
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    title = meta.get("title", f"抖音视频 {video_id}")
    duration = meta.get("duration", 0) or 0

    return DouyinFetchResult(
        video_id=video_id,
        title=title,
        duration=duration,
        video_path=video_path,
        audio_path=audio_path,
        meta_path=out_dir / "meta.json",
    )


# ---- 网页 / 文本源（D24：无视频输入）----

_HTML_STRIP = re.compile(r"<[^>]+>")
_BLANK_LINE = re.compile(r"\n{3,}")


def _clean_html(html: str) -> str:
    """从 HTML 中提取可读文本：去 script/style，取 body 正文，合并多余空行。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    body = soup.body or soup
    text = body.get_text(separator="\n", strip=True)
    text = _BLANK_LINE.sub("\n\n", text)
    return text.strip()


def fetch_webpage(
    source: str,
    out_dir: Path,
    *,
    timeout: float = 30.0,
) -> TextFetchResult:
    """抓取一个网页，提取正文写入 transcript.txt。

    source: 网页 URL（https 开头）。
    out_dir: 输出目录（自动建）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    r = requests.get(source, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"

    html = r.text
    text = _clean_html(html)

    # 取标题：优先 og:title → <title> → URL
    soup = BeautifulSoup(html, "html.parser")
    title = (
        _og_title(soup)
        or _tag_text(soup, "title")
        or source.rsplit("/", 1)[-1]
    )

    text_path = out_dir / "transcript.txt"
    text_path.write_text(text, encoding="utf-8")
    meta = {"url": source, "title": title, "charset": r.encoding or "utf-8"}
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return TextFetchResult(
        title=title,
        text=text,
        text_path=text_path,
        meta_path=out_dir / "meta.json",
    )


def _og_title(soup: BeautifulSoup) -> str:
    tag = soup.find("meta", property="og:title")
    if tag is None:
        return ""
    content = tag.get("content")
    return (str(content or "")).strip() if content else ""


def _tag_text(soup: BeautifulSoup, tag: str) -> str:
    el = soup.find(tag)
    return (el.get_text(strip=True) or "") if el else ""


def fetch_text(
    source: str,
    out_dir: Path,
    *,
    title: str = "",
) -> TextFetchResult:
    """将裸文本或文件内容写入 transcript.txt。

    source: 文本内容，或 .txt/.md/.pdf 文件的路径。
    out_dir: 输出目录（自动建）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    path = Path(source)
    if path.exists() and path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        title = title or path.stem
    else:
        text = source
        title = title or "直接输入文本"

    text_path = out_dir / "transcript.txt"
    text_path.write_text(text, encoding="utf-8")
    meta = {"title": title, "source": "direct" if not path.exists() else str(path)}
    (out_dir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return TextFetchResult(
        title=title,
        text=text,
        text_path=text_path,
        meta_path=out_dir / "meta.json",
    )


# ---- YouTube 源 ----

YOUTUBE_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{11})")


def parse_youtube_id(s: str) -> str:
    """从完整 URL 里提取 YouTube 视频 ID（11 位字母数字_-）。"""
    m = YOUTUBE_RE.search(s)
    if not m:
        raise ValueError(f"未找到 YouTube 视频 ID: {s!r}")
    return m.group(1)


def _yt_dlp_run(out_dir: Path, extra_args: list[str], source: str) -> Path:
    """跑 yt-dlp，返回下载的文件路径（.mp4 或信息 json 路径）。"""
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
    _run(cmd)
    return video_tmp


def fetch_youtube(source: str, out_dir: Path) -> YoutubeFetchResult:
    """获取一个 YouTube 视频为 video.mp4 + audio.mp3 + 自动字幕 (.vtt)。

    source: 完整 URL（youtube.com/watch?v=... 或 youtu.be/...）。
    out_dir: 输出目录（自动建）。
    自动提取 zh-Hans/zh-Hant/en 字幕（若可用）。
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
    _run(
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
        (out_dir / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 读取元数据拿标题和时长
    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    title = meta.get("title", f"YouTube 视频 {video_id}")
    duration = meta.get("duration", 0) or 0

    return YoutubeFetchResult(
        video_id=video_id,
        title=title,
        duration=duration,
        video_path=video_path,
        audio_path=audio_path,
        subtitle_path=subtitle_path,
        meta_path=out_dir / "meta.json",
    )


def _find_subtitle(out_dir: Path) -> Path | None:
    """找 yt-dlp 下载的自动字幕 .vtt 文件（优先级：zh-Hans > zh > en > 任意 .vtt）。"""
    for lang in ("zh-Hans", "zh", "en"):
        candidate = out_dir / f"video_tmp.{lang}.vtt"
        if candidate.exists():
            return candidate
    vtt_files = list(out_dir.glob("*.vtt"))
    return vtt_files[0] if vtt_files else None


# ---- 直接运行：python -m skillbrew.ingest <url|文本> [out_dir] ----
def _main() -> int:
    import sys

    if len(sys.argv) < 2:
        print("用法: python -m skillbrew.ingest <B站URL/BV号|抖音URL/ID|网页URL|文本/文件> [输出目录]")
        return 1
    src = sys.argv[1]

    # 自动识别平台
    if "bilibili.com" in src or src.startswith("BV"):
        # B站
        out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"data/sources/{parse_bvid(src)}")
        r = fetch_bilibili(src, out)
        print(f"[OK] {r.title}")
        print(f"     bvid={r.bvid} aid={r.aid} cid={r.cid} 时长={r.duration}s")
        print(f"     视频: {r.video_path} ({r.video_path.stat().st_size // 1024}KB)")
        print(f"     音频: {r.audio_path} ({r.audio_path.stat().st_size // 1024}KB)")
    elif "douyin.com" in src or src.isdigit():
        # 抖音
        video_id = parse_douyin_id(src) if src.isdigit() else None
        out = (
            Path(sys.argv[2])
            if len(sys.argv) > 2
            else Path(f"data/sources/douyin_{video_id or 'unknown'}")
        )
        r = fetch_douyin(src, out)  # type: ignore[assignment]
        print(f"[OK] {r.title}")
        print(f"     video_id={r.video_id} 时长={r.duration}s")  # type: ignore[attr-defined]
        print(f"     视频: {r.video_path} ({r.video_path.stat().st_size // 1024}KB)")
        print(f"     音频: {r.audio_path} ({r.audio_path.stat().st_size // 1024}KB)")
    elif src.startswith("http://") or src.startswith("https://"):
        # 网页
        out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"data/sources/web_{hash(src) & 0xFFFFFFFF:08x}")
        r = fetch_webpage(src, out)  # type: ignore[assignment]
        print(f"[OK] {r.title}")
        print(f"     正文长度: {len(r.text)} 字")  # type: ignore[attr-defined]
        print(f"     输出: {r.text_path}")  # type: ignore[attr-defined]
    else:
        # 当成纯文本或文件路径
        src_label = Path(src).name if Path(src).exists() else "直接输入"
        out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"data/sources/text_{hash(src) & 0xFFFFFFFF:08x}")
        r = fetch_text(src, out, title=src_label)  # type: ignore[assignment]
        print(f"[OK] {r.title}")
        print(f"     正文长度: {len(r.text)} 字")  # type: ignore[attr-defined]
        print(f"     输出: {r.text_path}")  # type: ignore[attr-defined]
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
