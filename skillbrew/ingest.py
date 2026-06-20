"""ingest：采集 + 获取（各源 adapter）。

当前实现 B站 adapter。**关键经验**：本机对 `www.bilibili.com` 网页层返回
HTTP 412（yt-dlp 也被拦），但 `api.bilibili.com` 公开 API 全通。故绕开 yt-dlp，
直接走公开 API：

  ① view    `x/web-interface/view?bvid=`        → 元数据(aid/cid/title)
  ② playurl `x/player/playurl?avid=&cid=&qn=&fnval=16&fourk=1`  ← **非 WBI**，免签名
     返回 DASH 流：dash.video[] / dash.audio[]，每条带 baseUrl
  ③ 选流：视频取 codecs 以 `avc1` 开头里带宽最高者(ffmpeg 可 -c copy 直接重封装)；
          音频取带宽最低者(语音不需要高码率)
  ④ 下载 video.m4s / audio.m4s（须带 Referer 头）→ ffmpeg 重封装
       video.m4s → video.mp4 (-c copy)
       audio.m4s → audio.mp3 (-vn -c:a libmp3lame -q:a 4)

换源(抖音/YouTube)只需新增 adapter，主流程不变。
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from dataclasses import dataclass
from pathlib import Path

BVID_RE = re.compile(r"BV[0-9A-Za-z]{10}")
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
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-i", str(v_m4s), "-c", "copy", str(video_path)])
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
          "-i", str(a_m4s), "-vn", "-c:a", "libmp3lame", "-q:a", "4", str(audio_path)])

    return BiliFetchResult(
        bvid=bvid, aid=aid, cid=cid, title=info["title"],
        duration=info.get("duration", 0), pic=info.get("pic", ""),
        video_path=video_path, audio_path=audio_path, meta_path=out_dir / "meta.json",
    )


# ---- 直接运行：python -m skillbrew.ingest <url> [out_dir] ----
def _main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m skillbrew.ingest <B站URL或BV号> [输出目录]")
        return 1
    src = sys.argv[1]
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(f"data/sources/{parse_bvid(src)}")
    r = fetch_bilibili(src, out)
    print(f"[OK] {r.title}")
    print(f"     bvid={r.bvid} aid={r.aid} cid={r.cid} 时长={r.duration}s")
    print(f"     视频: {r.video_path} ({r.video_path.stat().st_size//1024}KB)")
    print(f"     音频: {r.audio_path} ({r.audio_path.stat().st_size//1024}KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
