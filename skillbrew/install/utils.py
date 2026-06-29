"""install 包的通用小工具：时间戳、HTTP 下载、路径安全。"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from pathlib import Path

UA = "skillbrew"  # GitHub raw 也要求带 User-Agent
_TIMEOUT = 30.0
_MAX_RETRIES = 3  # 5xx/网络瞬时错误重试（raw 偶发 504，同 verify._get）
_RETRY_BACKOFF = 2.0


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def _fetch_bytes(url: str) -> bytes:
    """下载文件字节；5xx 与网络瞬时错误退避重试（策略同 verify._get）。"""
    for attempt in range(_MAX_RETRIES):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if 500 <= e.code < 600 and attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BACKOFF * (attempt + 1))
                continue  # 5xx 网关瞬时错误，退避后重试
            raise RuntimeError(f"下载失败 {e.code} {url}") from e
        except urllib.error.URLError as e:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BACKOFF * (attempt + 1))
                continue  # 网络抖动，重试
            raise RuntimeError(f"网络失败 {url}: {e}") from e
    raise RuntimeError(f"下载重试用尽 {url}")


def _rel_within(skill_dir_path: str, file_path: str) -> Path:
    """把仓库里的 file_path 转成 skill 目录内的相对路径，用于落地。

    skill_dir_path='skills/engineering/tdd'，file_path='skills/engineering/tdd/mocking.md'
    → Path('mocking.md')。防路径穿越：拒绝绝对路径与 .. 。
    """
    prefix = skill_dir_path.rstrip("/") + "/"
    rel = file_path[len(prefix) :] if file_path.startswith(prefix) else Path(file_path).name
    p = Path(rel)
    if p.is_absolute() or any(part == ".." for part in p.parts):
        raise RuntimeError(f"可疑路径，拒绝写入：{file_path}")
    return p
