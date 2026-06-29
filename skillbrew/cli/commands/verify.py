"""`verify` 子命令：溯源纠正 + 出机器安装清单。"""

from __future__ import annotations

import argparse
import logging
import traceback

from skillbrew.config import load_config

from ..utils import _resolve_source

logger = logging.getLogger(__name__)


def cmd_verify(args: argparse.Namespace) -> int:
    """溯源：回 GitHub 取一手资料，纠正草稿计划 + 出机器安装清单（不安装）。"""
    from skillbrew import verify as verify_mod

    cfg = load_config()  # 校验配置（verify 不用 LLM，但保持路径解析一致）
    src = _resolve_source(cfg, args.source)
    if not (src / "plan.json").exists():
        print(f"[ERR] {src} 没有 plan.json（先跑 plan）")
        return 1

    print(f"[溯源] {src}")

    def on_progress(s: dict, i: int, n: int) -> None:
        form = s.get("form", "Skill")
        cat = s.get("category", "")
        head = f"{cat}/" if cat else ""
        if form == "MCP":
            mcp = s.get("mcp") or {}
            logger.info(
                "[%d/%d] 解析 MCP %s（%s）...",
                i + 1, n, s["name"], mcp.get("transport", "stdio"),
            )
        elif form == "repo":
            logger.info("[%d/%d] 探仓库 %s ...", i + 1, n, s.get("repo", "") or s["name"])
        else:
            logger.info("[%d/%d] 取 %s%s SKILL.md ...", i + 1, n, head, s["name"])

    try:
        summary = verify_mod.verify(src, repo_override=args.repo, on_progress=on_progress)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print(f"[FAIL] 溯源失败：{e}")
        return 2

    print("\n" + "=" * 60)
    form = summary.get("form", "Skill")
    if form == "MCP":
        print(
            f"✅ MCP 形态核实：解析命中 {summary['item_total']} 个 / unresolved {summary.get('unresolved_count', 0)} 个"
        )
        print(f"   安装清单：{summary['install_list']}")
    elif form == "repo":
        print(
            f"✅ repo 形态核实：待 clone 仓库 {summary['item_total']} 个 / unresolved {summary.get('unresolved_count', 0)} 个"
        )
        print(f"   安装清单：{summary['install_list']}")
    else:
        print(
            f"✅ 一手核实：{summary['verified_repo']}（⭐{summary['stars']}，{summary['stars_observed_at']}）"
        )
        print(f"   定位方式：{summary['how_resolved']}")
        print(f"   全仓 skill：{summary['skill_total']} 个 → {summary['install_list']}")
    print(f"   plan.json 纠正 {len(summary['corrections'])} 处：")
    for c in summary["corrections"]:
        print(f"     - {c}")
    print("=" * 60)
    print("刹车：到此只核实 + 出安装清单，未安装。安装需另跑 install 并单独授权。")
    return 0
