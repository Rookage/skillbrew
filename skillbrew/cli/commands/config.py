"""`config` 子命令：打印解析后的配置（key 脱敏）。"""

from __future__ import annotations

import argparse

from skillbrew.config import load_config

from ..utils import _print_config


def cmd_config(_args: argparse.Namespace) -> int:
    cfg = load_config()
    print("skillbrew 配置（key 已脱敏）：")
    _print_config(cfg)
    return 0
