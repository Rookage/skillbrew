"""`dedup` 子命令：本地基准比对，判定 new/merge/skip。"""

from __future__ import annotations

import argparse
import traceback
from pathlib import Path

from skillbrew import config
from skillbrew.config import load_config

from ..utils import _resolve_source


def cmd_dedup(args: argparse.Namespace) -> int:
    """去重：扫本地已装 skill 建基准 → 比 install_list → 判 new/merge/skip（不安装）。"""
    from skillbrew import dedup as dedup_mod

    cfg = load_config()  # 校验配置 + 路径解析一致（dedup 不用 LLM）
    src = _resolve_source(cfg, args.source)
    if not (src / "install_list.json").exists():
        print(f"[ERR] {src} 没有 install_list.json（先跑 verify）")
        return 1

    # D18：扫本地优先 —— 默认含用户级 skill 目录，自动检测当前工作目录的 .claude/skills/
    skill_dirs = [config.skills_dir()]
    # 自动检测当前工作目录及其父目录的 .claude/skills/（项目级 skill；跨运行时共享约定，保留）
    for parent in [Path.cwd()] + list(Path.cwd().parents):
        proj_skills = parent / ".claude" / "skills"
        if proj_skills.exists() and proj_skills not in skill_dirs:
            skill_dirs.append(proj_skills)
            break  # 找到最近的一个就停
    # --skills-dir 可追加其他目录
    skill_dirs += [Path(d) for d in (args.skills_dir or [])]

    print(f"[去重] {src}")
    print(f"   扫描基准目录：{[str(d) for d in skill_dirs]}")

    def on_progress(stage: str, n) -> None:
        if stage == "classify":
            print(f"   逐项比对 install_list {n} 个能力 ...", flush=True)

    try:
        summary = dedup_mod.dedup(src, skill_dirs=skill_dirs, on_progress=on_progress)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print(f"[FAIL] 去重失败：{e}")
        return 2

    bc = summary["baseline"]["counts"]
    s = summary["summary"]
    print("\n" + "=" * 60)
    print(
        f"基准：{bc['distinct']} 个 distinct skill（磁盘 {bc['disk_entries']} + 台账 {bc['registry_rows']} 行）"
    )
    print(f"      状态分布：{bc['by_status']}")
    print(f"install_list {s['total']} 项判定：new={s['new']}  merge={s['merge']}  skip={s['skip']}")
    print(f"报告 → {summary['dedup_path']}")
    merges = [d for d in summary["decisions"] if d["decision"] == "merge"]
    if merges:
        print("\nmerge 候选（建议人工确认整并，不自动决定）：")
        for d in merges:
            print(f"  - {d['name']} → {d['target']}  [{', '.join(d.get('shared', []))}]")
    print("=" * 60)
    print("刹车：到此只判定 + 出报告，未安装。安装需另跑 install 并单独授权。")
    return 0
