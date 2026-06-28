"""`recommend` 子命令：判断步，给出安装建议名单。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from skillbrew import config, llm
from skillbrew.config import load_config

from ..utils import _resolve_source


def cmd_recommend(args: argparse.Namespace) -> int:
    """判断步（recommend）：去重之后、安装之前，判「值不值得装」（D19 判断先行）。

    读 dedup.json（new/merge/skip 决策）+ install_list.json（候选描述），扫本机能力画像，
    按 --mode 给 new 候选打分/勾选 → 出 recommend.json（approved 名单）。不安装、不改台账。
    keyword/manual 纯本地不烧 token；ai 属积木 D（调文本模型，烧 token，需用户在场，暂未接线）。
    """
    from skillbrew import recommend as rec

    cfg = load_config()  # 校验配置 + 路径解析一致（keyword/manual 不用 LLM）
    src = _resolve_source(cfg, args.source)
    if not (src / "dedup.json").exists():
        print(f"[ERR] {src} 没有 dedup.json（先跑 dedup）")
        return 1
    if not (src / "install_list.json").exists():
        print(f"[ERR] {src} 没有 install_list.json（先跑 verify）")
        return 1

    mode = args.mode
    if mode == rec.MODE_AI:
        # D21 前置：文本模型配置须完整，否则不烧 token、不走死路（提示用 keyword/manual）
        if not cfg.text.is_complete:
            print(
                "[ERR] ai 模式需文本模型配置（D21 前置），但 .env 缺 base_url/api_key/model 之一。"
            )
            print(f"      text={cfg.text.key_masked}")
            print(
                "      请先补 .env，或改用 --mode keyword（规则打分）/ --mode manual（人工勾选），都不烧 token。"
            )
            return 1

    # ---- 读一手数据 ----
    dedup_data = json.loads((src / "dedup.json").read_text(encoding="utf-8"))
    ilist = json.loads((src / "install_list.json").read_text(encoding="utf-8"))
    decisions = dedup_data.get("decisions", [])
    # 描述 + usability 形态无关地取（MCP 项无 description，须用 capability_name+invoke_hint 拼对等描述，
    # 否则 score_keyword 扣「无描述」误杀；usability 须从 install_list 透传，dedup decision 不带）
    descriptions = rec.build_descriptions(ilist)
    usability_map = rec.build_usability(ilist)

    # ---- 本机能力画像（D18 动态基准，复用 dedup 扫描口径）----
    skill_dirs = [config.skills_dir()]
    # 自动检测当前工作目录及其父目录的 .claude/skills/（项目级 skill；跨运行时共享约定，保留）
    for parent in [Path.cwd()] + list(Path.cwd().parents):
        proj_skills = parent / ".claude" / "skills"
        if proj_skills.exists() and proj_skills not in skill_dirs:
            skill_dirs.append(proj_skills)
            break  # 找到最近的一个就停
    skill_dirs += [Path(d) for d in (args.skills_dir or [])]
    print(f"[判断步] {src}  mode={mode}")
    print(f"   画像扫描目录：{[str(d) for d in skill_dirs]}")
    profile = rec.build_profile(skill_dirs)
    print(f"   本机画像：distinct={profile.distinct}  分类分布={profile.by_category}")

    # ---- 按 mode 给 new 候选打分 / 人工勾选 / ai 判断 ----
    if mode == rec.MODE_KEYWORD:
        new_js = rec.score_keyword_batch(
            decisions, profile, descriptions=descriptions, usability=usability_map
        )
    elif mode == rec.MODE_AI:
        print(
            f"   [ai] 烧 token 调文本模型 {cfg.text.model}，分批判断（用户在场监控；--limit={args.limit}）..."
        )

        def _on_batch(i, n, bs, ok):
            tag = "ok" if ok else "FAIL→整批降级「不值得装」"
            print(f"   [ai] 批 {i}/{n}（{bs} 条）→ {tag}")

        new_js = rec.judge_ai(
            decisions,
            profile,
            descriptions=descriptions,
            usability=usability_map,
            cfg=cfg,
            chat_fn=llm.chat_text,
            limit=args.limit,
            on_batch=_on_batch,
        )
    else:  # manual
        new_js = rec.pick_manual(decisions, descriptions=descriptions, usability=usability_map)

    # ---- 合并 skip/merge（trivial 兜底）+ 装配报告 ----
    judgments = rec.merge_judgments(decisions, new_js)
    report = rec.assemble_report(
        decisions,
        judgments,
        mode=mode,
        source_video=dedup_data.get("source_video", ""),
        repo=dedup_data.get("install_list_repo", "") or ilist.get("verified_repo", ""),
        source_skip_reason=args.source_skip or "",
    )

    out_path = src / "recommend.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 打印汇总（D22 反盲盒：说清源级建议 + approved 子集）----
    sv = report["source_verdict"]
    sm = report["summary"]
    print("\n" + "=" * 60)
    print(f"源级建议：{sv}" + (f"（理由：{args.source_skip}）" if args.source_skip else ""))
    print(
        f"候选汇总：total={sm['total']}  by_verdict={sm['by_verdict']}  approved={sm['approved']}"
    )
    approved = report["approved"]
    shown = approved[:20]
    print(
        f"approved（install 该装的子集，D20 挑着买）：{shown}{' ...' if len(approved) > 20 else ''}"
    )
    print(f"报告 → {out_path}")
    print("=" * 60)
    print(
        "刹车：判断步只出 recommend.json，未安装。install 只装 approved 子集（须另跑 install --approve）。"
    )
    return 0
