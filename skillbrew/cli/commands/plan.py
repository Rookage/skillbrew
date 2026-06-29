"""`plan` 子命令：只跑消化（字幕 + 视觉 → 草稿计划）。"""

from __future__ import annotations

import argparse

from skillbrew.config import load_config

from ..utils import _resolve_source


def cmd_plan(args: argparse.Namespace) -> int:
    """只跑消化（字幕 + 视觉 → 草稿计划）。"""
    from skillbrew import plan

    cfg = load_config()  # 校验配置（digest 内部也会 load，这里先暴露配置问题）
    src = _resolve_source(cfg, args.source)
    p = plan.digest(src)
    print(f"[OK] 计划存 {src / 'plan.json'}")
    print(f"  标题：{p.get('source_title', '')}")
    caps = p.get("capabilities", [])
    print(f"  能力 {len(caps)} 项：")
    for c in caps:
        print(f"    - [{c.get('form', '?')}] {c.get('name', '')}")
    print("  （草稿，未安装）")
    return 0
