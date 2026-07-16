"""sources/ 内部共享工具：HTTP/ffmpeg 调用、UA、URL 解析等。

这些函数不对外，仅给同目录 adapter 模块调用。
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def get_json(url: str, headers: dict[str, str], timeout: float = 30.0) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def download(url: str, dest: Path, headers: dict[str, str], timeout: float = 120.0) -> None:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)


def run(cmd: list[str]) -> None:
    """跑外部命令（ffmpeg/yt-dlp），失败抛带 stderr 的错。"""
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(cmd)}\n{p.stderr[-800:]}")


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_short_url(url: str) -> str:
    """解析短链重定向，拿真实 URL。先 HEAD 失败再 GET。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.url
    except Exception:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.url
