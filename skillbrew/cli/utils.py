"""CLI 内部共享的轻量帮助函数。

命令模块通过相对导入复用，避免各命令文件重复实现。
"""

from __future__ import annotations

import shutil
import struct
import sys
import threading
import time
import zlib
from contextlib import contextmanager
from pathlib import Path

from skillbrew.config import Config
from skillbrew.errors import SkillbrewError

# ---- 外部二进制依赖（视频链路需要）----

# 每个工具的安装指引：(macOS, Debian/Ubuntu, Windows, 通用下载页)
_INSTALL_HINTS: dict[str, tuple[str, str, str, str]] = {
    "ffmpeg": (
        "brew install ffmpeg",
        "sudo apt install ffmpeg  (或 sudo dnf install ffmpeg)",
        "winget install Gyan.FFmpeg  (或从 https://ffmpeg.org/download.html 下载)",
        "https://ffmpeg.org/download.html",
    ),
    "yt-dlp": (
        "brew install yt-dlp",
        "sudo pip install -U yt-dlp  (或 sudo curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp -o /usr/local/bin/yt-dlp && sudo chmod a+rx /usr/local/bin/yt-dlp)",
        "winget install yt-dlp.yt-dlp",
        "https://github.com/yt-dlp/yt-dlp#installation",
    ),
}


def _require_binaries(*names: str) -> list[str]:
    """检查外部二进制是否在 PATH 里；返回缺失的工具名列表。

    用于 ingest/understand 等视频链路命令在真正干活前预检，避免
    下载完视频才发现 ffmpeg 没装导致崩 FileNotFoundError。
    """
    return [n for n in names if shutil.which(n) is None]


def _format_missing_hint(missing: list[str]) -> str:
    """把缺失工具列表+安装指引格式化成用户能直接复制粘贴的提示。"""
    import platform

    sysname = platform.system()
    if sysname == "Darwin":
        idx = 0
        os_label = "macOS"
    elif sysname == "Linux":
        idx = 1
        os_label = "Linux"
    elif sysname == "Windows":
        idx = 2
        os_label = "Windows"
    else:
        idx = 3
        os_label = sysname

    lines = ["[缺依赖] 以下外部工具未安装（视频链路必需）："]
    for n in missing:
        hints = _INSTALL_HINTS.get(n)
        lines.append(f"  - {n}")
        if hints:
            lines.append(f"      {os_label}: {hints[idx]}")
            if hints[3]:
                lines.append(f"      其他系统参考: {hints[3]}")
    lines.append("装好后重跑即可。")
    return "\n".join(lines)


# ---- CLI 进度反馈（stdlib 简易 spinner，非 TTY 降级两行）----
# P1-3：长耗时点（视觉看图/AI 推断/大仓溯源）需要"还在动"的提示，
# 不引 rich，避免加依赖；非 TTY（CI/重定向/管道）自动降级。


def _is_tty() -> bool:
    """stderr 接交互终端才开动画；否则降级成「开始…完成」两行。"""
    try:
        return bool(sys.stderr.isatty())
    except (AttributeError, ValueError):
        return False


@contextmanager
def _spinner(message: str, *, stream=sys.stderr):
    """上下文管理器：进入打「<msg>...」，TTY 下循环转 |/-\\，退出打 OK/FAIL。

    用法::

        with _spinner("看关键帧"):
            long_work()
    """
    is_tty = _is_tty()
    if is_tty:
        stream.write(f"{message} ... ")
        stream.flush()
    else:
        stream.write(f"{message} ... 开始\n")
        stream.flush()

    glyph = iter(["|", "/", "-", "\\"])
    stop = threading.Event()

    def _spin() -> None:
        while not stop.is_set():
            try:
                g = next(glyph)
            except StopIteration:
                return
            stream.write(f"\r{message} ... {g}")
            stream.flush()
            # 每 0.12s 一帧；stop 等待循环外的 set()
            stop.wait(0.12)

    t = threading.Thread(target=_spin, daemon=True) if is_tty else None
    if t:
        t.start()
    err: BaseException | None = None
    try:
        yield
    except BaseException as e:
        err = e
        raise
    finally:
        if t:
            stop.set()
            t.join(timeout=0.5)
            mark = "FAIL" if err else "OK"
            stream.write(f"\r{message} ... {mark}\n")
            stream.flush()
        else:
            mark = "FAIL" if err else "完成"
            stream.write(f"{message} ... {mark}\n")
            stream.flush()


def _print_progress(current: int, total: int, label: str = "", *, stream=sys.stderr) -> None:
    """TTY 下行内刷新 [i/n]，非 TTY 下每次换行一行（日志友好）。"""
    pct = f" ({100 * current // total}%)" if total else ""
    suffix = f" {label}" if label else ""
    line = f"  [{current}/{total}]{pct}{suffix}"
    if _is_tty():
        stream.write("\r" + line + "   ")  # 右补空格清掉旧行残留
        stream.flush()
        if current >= total:
            stream.write("\n")
            stream.flush()
    else:
        stream.write(line + "\n")
        stream.flush()


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
