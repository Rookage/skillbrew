"""skillbrew 命令行入口包。

用法：
  python -m skillbrew doctor          # 自检：配置 + 文本连通 + 视觉模型列表
  python -m skillbrew doctor --vision # 额外跑一次真·看图（Agnes ~5min/张）
  python -m skillbrew config          # 打印解析后的配置（key 脱敏）

pip install -e . 后也可直接 `skillbrew ...`。
CLI 用标准库 argparse（零新增依赖；后续可换 Typer，接口不变）。
"""

from __future__ import annotations

import sys
import traceback

from skillbrew.config import ensure_utf8_stdout
from skillbrew.errors import SkillbrewError

from .parser import parse_args


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
    traceback.print_exc()
    return 2


def main(argv: list[str] | None = None) -> int:
    # 入口统一 UTF-8：Windows 默认 GBK 控制台 print 含零宽字符会崩
    # 在最后一刻（issue #5）。统一 UTF-8+errors=replace，
    # 所有 print 都不会因编码炸。库式调用不受影响。
    ensure_utf8_stdout()
    try:
        args = parse_args(argv)
        return args.func(args)
    except SystemExit as e:
        # argparse 在 --help/--version 时会抛 SystemExit；原单文件直接透传给 sys.exit，
        # 这里保持同样的进程语义。
        code = e.code if isinstance(e.code, int) else 0
        return int(code)
    except BaseException as exc:  # noqa: BLE001
        return _exit_code(exc)
