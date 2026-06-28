"""`record` 子命令：从台账/清单/去重一手数据生成安装记录与看板（只读）。"""

from __future__ import annotations

import argparse
import json
import traceback
from pathlib import Path

from skillbrew import config
from skillbrew.config import load_config

from ..utils import _resolve_source


def cmd_record(args: argparse.Namespace) -> int:
    """记录+看板：从台账/清单/去重一手数据代码生成安装记录与看板（只读，不改台账）。"""
    from skillbrew import record as record_mod

    cfg = load_config()  # 校验配置 + 路径解析一致（record 不用 LLM，纯只读）
    src = _resolve_source(cfg, args.source)
    if not (src / "install_list.json").exists():
        print(f"[ERR] {src} 没有 install_list.json（先跑 verify）")
        return 1
    if not (src / "dedup.json").exists():
        print(f"[ERR] {src} 没有 dedup.json（先跑 dedup）")
        return 1

    # skill_dirs：默认交给 record 读 dedup.json 的 baseline.skill_dirs（与去重同口径）；
    # --skills-dir 为追加（dedup 默认目录 + 追加），避免漏扫默认两个目录。
    skill_dirs = None
    if args.skills_dir:
        dd = json.loads((src / "dedup.json").read_text(encoding="utf-8"))
        base = dd.get("baseline", {}).get("skill_dirs", []) or [str(config.skills_dir())]
        skill_dirs = [Path(d) for d in base] + [Path(d) for d in args.skills_dir]

    print(f"[记录+看板] {src}")

    def on_progress(stage: str, n) -> None:
        if stage == "read":
            print(f"   扫描磁盘目录：{[str(d) for d in (n or [])]}")
        elif stage == "write":
            print("   生成 RECORD.md + DASHBOARD.md ...")

    try:
        r = record_mod.record(src, skill_dirs=skill_dirs, on_progress=on_progress)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print(f"[FAIL] 记录失败：{e}")
        return 2

    ig = r["integrity"]
    print("\n" + "=" * 60)
    # 形态分支：repo 的 verified_repo 为空（identity 取自 items[0]），按形态显示
    il = json.loads((src / "install_list.json").read_text(encoding="utf-8"))
    form = il.get("form", "Skill")
    if form == "repo":
        its = il.get("items") or il.get("skills") or []
        ri = its[0] if its else {}
        stars = ri.get("stars")
        star_tag = f"（⭐{stars}）" if stars is not None else ""
        print(f"✅ 代码生成完成：repo 形态 {ri.get('repo', '')} {star_tag}")
    elif form == "MCP":
        its = il.get("items") or il.get("skills") or []
        print(f"✅ 代码生成完成：MCP 形态，命中 {len(its)} 个能力")
    else:
        print(f"✅ 代码生成完成：仓库 {r['verified_repo']}")
    print(f"   本源安装会话：{r['sessions']} 次；本次新装 {len(r['this_run_installed'])} 个")
    print(
        f"   落盘核对：磁盘 {ig['disk_active_distinct']} == 台账 {ig['registry_active']}"
        f" → {'✅一致' if ig['ok'] else '⚠️不一致'}"
    )
    if ig["orphans"]:
        print(f"   孤儿（磁盘有/台账无）：{ig['orphans']}")
    if ig["missing"]:
        print(f"   缺失（台账有/磁盘无）：{ig['missing']}")
    print(f"   记录 → {r['record_path']}")
    print(f"   看板 → {r['dashboard_path']}")
    print("=" * 60)
    print("刹车：record 只读，未改台账、未下载、未调 LLM。")
    return 0
