"""CLI 内部共享的轻量帮助函数。

命令模块通过相对导入复用，避免各命令文件重复实现。
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

from skillbrew.config import Config
from skillbrew.errors import SkillbrewError


def _print_config(cfg: Config) -> None:
    exists = "存在" if cfg.env_path.exists() else "缺失"
    print(f"  .env      = {cfg.env_path}  ({exists})")
    print(f"  仓库根     = {cfg.root}")
    for name, p in (("文本 TEXT", cfg.text), ("视觉 VISION", cfg.vision)):
        print(
            f"  [{name}] base_url={p.base_url or '(未配置)'}  "
            f"model={p.model or '(未配置)'}  key={p.key_masked}"
        )


def _check_present(cfg: Config) -> bool:
    """D21：文本必备（缺则返回 False→FAIL）；视觉可选（缺只 WARN+降级提示，不影响返回值）。"""
    ok = True
    if cfg.text.missing:
        ok = False
        print(f"  [缺] TEXT 组缺少: {', '.join(cfg.text.missing)}（文本模型必备，D21）")
    if cfg.vision.missing:
        print(
            f"  [WARN] VISION 组缺少: {', '.join(cfg.vision.missing)}（视觉可选，将降级「视频转语音→转文字」，D21）"
        )
    return ok


def _make_half_half_png(w: int = 120, h: int = 120) -> bytes:
    """标准库手搓一张「左红右蓝」PNG。模型答出此布局即证明真看图。"""

    def chunk(typ: bytes, data: bytes) -> bytes:
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    half = w // 2
    red, blue = bytes([255, 0, 0]), bytes([0, 0, 255])
    raw = b"".join(b"\x00" + red * half + blue * (w - half) for _ in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _resolve_source(cfg: Config, s: str) -> Path:
    """BV号/URL → data/sources/<bvid>；否则当成源目录路径。"""
    import skillbrew.ingest as _ingest

    if _ingest.BVID_RE.search(s):
        return cfg.data_dir / "sources" / _ingest.parse_bvid(s)
    return Path(s)


def _exit_code(exc: BaseException) -> int:
    """把异常映射到进程退出码，给 main() 用。"""
    if isinstance(exc, SkillbrewError):
        print(f"\n[FAIL] {exc}", file=sys.stderr)
        if exc.hint:
            print(f"  → {exc.hint}", file=sys.stderr)
        return 1
    if isinstance(exc, KeyboardInterrupt):
        print("\n中断。", file=sys.stderr)
        return 130
    # 非预期异常：完整 traceback 供调试
    import traceback as _tb

    _tb.print_exc()
    return 2
