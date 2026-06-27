"""skillbrew 命令行入口。

用法：
  python -m skillbrew doctor          # 自检：配置 + 文本连通 + 视觉模型列表
  python -m skillbrew doctor --vision # 额外跑一次真·看图（Agnes ~5min/张）
  python -m skillbrew config          # 打印解析后的配置（key 脱敏）

pip install -e . 后也可直接 `skillbrew ...`。
CLI 用标准库 argparse（零新增依赖；后续可换 Typer，接口不变）。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import struct
import sys
import tempfile
import time
import traceback
import warnings
import zlib
from pathlib import Path

from . import __version__
from . import config
from . import llm
from . import notify
from .config import Config, ensure_utf8_stdout, load_config
from .errors import SkillbrewError


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
        print(f"  [WARN] VISION 组缺少: {', '.join(cfg.vision.missing)}（视觉可选，将降级「视频转语音→转文字」，D21）")
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


def cmd_config(_args: argparse.Namespace) -> int:
    cfg = load_config()
    print("skillbrew 配置（key 已脱敏）：")
    _print_config(cfg)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    print(f"skillbrew {__version__} 自检")
    print("=" * 60)
    cfg = load_config()
    _print_config(cfg)
    print("-" * 60)
    text_ok = _check_present(cfg)

    # ---- 判断步 recommend 可用性（D21：无 key 不走死路，keyword/manual 恒可用）----
    from . import recommend
    print("\n[判断步 recommend] 三模式可用性：")
    for line in recommend.recommend_health(cfg):
        print("   -", line)

    if not text_ok:
        print("\n[FAIL] 文本模型必备（D21）。keyword/manual 判断步仍可用；请检查 .env（参考 .env.example）。")
        return 1

    # ---- 文本组 ----
    print("\n[文本组] 列模型 (GET /models)：")
    try:
        for i in llm.list_models(cfg.text):
            print("   -", i)
    except Exception as e:  # 列模型非关键，失败不阻塞
        print("   [WARN] 列模型失败:", repr(e)[:200])

    print("[文本组] 实测对话：")
    t0 = time.time()
    try:
        reply = llm.chat_text(
            cfg, "用一句话介绍你自己，并说出你的模型名。", timeout=60
        )
        print(f"   [OK] {time.time() - t0:.1f}s -> {reply}")
    except SkillbrewError as e:
        print(f"   [WARN] {e}")
        if e.hint:
            print(f"   → {e.hint}")
    except Exception as e:
        traceback.print_exc()
        print(f"   [FAIL] {time.time() - t0:.1f}s ->", repr(e)[:300])
        return 2

    # ---- 视觉组（D21：可选，缺则降级不 fail）----
    if not cfg.vision.is_complete:
        print("\n[视觉组] 未配置 → 降级模式（视频转语音→语音转文字，D21）。")
        print("   建议配多模态模型启用关键帧看图，但不阻断主流程。")
    else:
        print("\n[视觉组] 列模型 (GET /models)：")
        try:
            for i in llm.list_models(cfg.vision):
                print("   -", i)
        except Exception as e:
            print("   [WARN] 列模型失败:", repr(e)[:200])

        if args.vision:
            print("\n[视觉组] 实测真·看图（生成左红右蓝图，Agnes ~5min，请耐心）...")
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            tmp.write(_make_half_half_png())
            tmp.close()
            t0 = time.time()
            try:
                reply = llm.chat_vision(
                    cfg, "这张图里有哪些颜色？怎么排列的？一句话回答。", tmp.name
                )
                print(f"   [OK] {time.time() - t0:.1f}s -> {reply}")
                print("   (期望：左红右蓝 —— 答对即证明模型真在看图)")
            except Exception as e:
                traceback.print_exc()
                print(f"   [FAIL] {time.time() - t0:.1f}s ->", repr(e)[:300])
            finally:
                os.unlink(tmp.name)
        else:
            print("\n[视觉组] 跳过真·看图实测（加 --vision 跑，Agnes ~5min/张）")

    print("\n" + "=" * 60)
    print("自检完成。")
    return 0


# ---- 主流程子命令：run / ingest / understand / plan ----

def _resolve_source(cfg: Config, s: str) -> Path:
    """BV号/URL → data/sources/<bvid>；否则当成源目录路径。"""
    from . import ingest
    if ingest.BVID_RE.search(s):
        return cfg.data_dir / "sources" / ingest.parse_bvid(s)
    return Path(s)


def cmd_run(args: argparse.Namespace) -> int:
    """一键：采集 → 理解(字幕+关键帧+视觉) → 消化 → 草稿计划，到此为止不安装。"""
    from . import ingest, understand, plan

    cfg = load_config()
    bvid = ingest.parse_bvid(args.source)
    src_dir = cfg.data_dir / "sources" / bvid
    src_dir.mkdir(parents=True, exist_ok=True)
    print(f"源: {bvid}  目录: {src_dir}")

    # ① 采集
    have_media = (src_dir / "video.mp4").exists() and (src_dir / "audio.mp3").exists()
    if not args.force and have_media:
        print("[①采集] 已存在，跳过")
    else:
        print("[①采集] 下载 ...")
        r = ingest.fetch_bilibili(args.source, src_dir, qn=args.qn)
        print(f"   -> {r.title}（时长 {r.duration}s）")

    # ② 字幕 ASR
    _EMPTY_TRANSCRIPT = '{"segments":[],"text":"","language":""}'
    _EMPTY_TRANSCRIPT = '{"segments":[],"text":"","language":""}'
    if args.skip_asr:
        print("[②字幕] --skip-asr 跳过")
        _tp = src_dir / "transcript.json"
        if not _tp.exists():
            _tp.write_text(_EMPTY_TRANSCRIPT, encoding="utf-8")
            (src_dir / "transcript.txt").write_text("", encoding="utf-8")
        _tp = src_dir / "transcript.json"
        if not _tp.exists():
            _tp.write_text(_EMPTY_TRANSCRIPT, encoding="utf-8")
            (src_dir / "transcript.txt").write_text("", encoding="utf-8")
    elif not args.force and (src_dir / "transcript.json").exists():
        print("[②字幕] 已存在，跳过")
    else:
        print("[②字幕] ASR 转写（首次加载模型~160s）...")
        t = understand.transcribe(src_dir / "audio.mp3", src_dir)
        print(f"   -> {len(t['segments'])} 段, {len(t['text'])} 字")

    # ③ 关键帧
    if not args.force and (src_dir / "keyframes_align.json").exists():
        print("[③关键帧] 已存在，跳过")
    else:
        print(f"[③关键帧] farthest-point 采样 {args.max_frames} 帧 ...")
        kfs = understand.select_keyframes(src_dir / "video.mp4", src_dir, max_frames=args.max_frames)
        align = understand.align_keyframes(src_dir / "transcript.json", kfs)
        (src_dir / "keyframes_align.json").write_text(
            json.dumps(align, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"   -> {len(kfs)} 张")

    # ④ 视觉看图
    if args.skip_vision:
        print("[④视觉] --skip-vision 跳过")
    elif not args.force and (src_dir / "keyframe_visions.json").exists():
        print("[④视觉] 已存在，跳过")
    else:
        print(f"[④视觉] 看关键帧（Agnes ~5min/张，并发 {args.max_workers}）...")
        res = understand.describe_keyframes(cfg, src_dir, max_workers=args.max_workers)
        ok = sum(1 for r in res if r["ok"])
        print(f"   -> {ok}/{len(res)} 张成功")
        if ok < len(res):
            print("   ⚠️ 部分帧失败，草稿计划将只基于成功的视觉描述 + 字幕")

    # ⑤ 消化 → 草稿计划
    if not args.force and (src_dir / "plan.json").exists():
        print("[⑤消化] 计划已存在，跳过（--force 可重跑）")
    else:
        print("[⑤消化] DeepSeek 融合字幕 + 视觉 → 计划 ...")
        plan.digest(src_dir)

    # 摘要
    p = json.loads((src_dir / "plan.json").read_text(encoding="utf-8"))
    print("\n" + "=" * 60)
    print(f"草稿计划已生成：{src_dir / 'plan.json'}")
    print(f"标题：{p.get('source_title', '')}")
    caps = p.get("capabilities", [])
    print(f"能力 {len(caps)} 项：")
    for c in caps:
        print(f"  - [{c.get('form', '?')}] {c.get('name', '')}")
    print("=" * 60)
    print("刹车：到此为止，未安装任何东西。安装需另跑 install 并单独授权。")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """只跑采集（下载视频 + 音频）。"""
    from . import ingest

    cfg = load_config()
    src = args.source

    # 自动识别平台
    if "bilibili.com" in src or src.startswith("BV"):
        # B站
        bvid = ingest.parse_bvid(src)
        src_dir = cfg.data_dir / "sources" / bvid
        r = ingest.fetch_bilibili(src, src_dir, qn=args.qn)
        print(f"[OK] {r.title}")
        print(f"     bvid={r.bvid} 时长={r.duration}s")
        print(f"     视频: {r.video_path} ({r.video_path.stat().st_size // 1024}KB)")
        print(f"     音频: {r.audio_path} ({r.audio_path.stat().st_size // 1024}KB)")
    elif "douyin.com" in src or src.isdigit():
        # 抖音：先解析短链拿真实 URL，再提取 video_id
        if "v.douyin.com" in src:
            src = ingest._resolve_short_url(src)
        video_id = ingest.parse_douyin_id(src)
        src_dir = cfg.data_dir / "sources" / f"douyin_{video_id}"
        r = ingest.fetch_douyin(src, src_dir)
        print(f"[OK] {r.title}")
        print(f"     video_id={r.video_id} 时长={r.duration}s")
        print(f"     视频: {r.video_path} ({r.video_path.stat().st_size // 1024}KB)")
        print(f"     音频: {r.audio_path} ({r.audio_path.stat().st_size // 1024}KB)")
    else:
        print(f"[ERR] 未识别的平台: {src}")
        return 1
    return 0


def cmd_understand(args: argparse.Namespace) -> int:
    """只跑理解（字幕 + 关键帧 + 视觉）。"""
    from . import understand

    cfg = load_config()
    src = _resolve_source(cfg, args.source)
    if not (src / "video.mp4").exists():
        print(f"[ERR] {src} 没有 video.mp4（先跑 ingest）")
        return 1

    if args.skip_asr:
        print("[字幕] --skip-asr 跳过")
        if not (src / "transcript.json").exists():
            _EMPTY = '{"segments":[],"text":"","language":""}'
            (src / "transcript.json").write_text(_EMPTY, encoding="utf-8")
            (src / "transcript.txt").write_text("", encoding="utf-8")
    elif not args.force and (src / "transcript.json").exists():
        print("[字幕] 已存在，跳过")
    else:
        print("[字幕] ASR 转写 ...")
        t = understand.transcribe(src / "audio.mp3", src)
        print(f"   -> {len(t['segments'])} 段, {len(t['text'])} 字")

    if not args.force and (src / "keyframes_align.json").exists():
        print("[关键帧] 已存在，跳过")
    else:
        print(f"[关键帧] 采样 {args.max_frames} 帧 ...")
        kfs = understand.select_keyframes(src / "video.mp4", src, max_frames=args.max_frames)
        align = understand.align_keyframes(src / "transcript.json", kfs)
        (src / "keyframes_align.json").write_text(
            json.dumps(align, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"   -> {len(kfs)} 张")

    if args.skip_vision:
        print("[视觉] --skip-vision 跳过")
    elif not args.force and (src / "keyframe_visions.json").exists():
        print("[视觉] 已存在，跳过")
    else:
        print(f"[视觉] 看关键帧（并发 {args.max_workers}）...")
        res = understand.describe_keyframes(cfg, src, max_workers=args.max_workers)
        ok = sum(1 for r in res if r["ok"])
        print(f"   -> {ok}/{len(res)} 张成功")

    print(f"[OK] → {src}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """只跑消化（字幕 + 视觉 → 草稿计划）。"""
    from . import plan

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


def cmd_verify(args: argparse.Namespace) -> int:
    """溯源：回 GitHub 取一手资料，纠正草稿计划 + 出机器安装清单（不安装）。"""
    from . import verify as verify_mod

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
            print(f"   [{i + 1}/{n}] 解析 MCP {s['name']}"
                  f"（{mcp.get('transport', 'stdio')}）...", flush=True)
        elif form == "repo":
            print(f"   [{i + 1}/{n}] 探仓库 {s.get('repo', '') or s['name']} ...", flush=True)
        else:
            print(f"   [{i + 1}/{n}] 取 {head}{s['name']} SKILL.md ...", flush=True)

    try:
        summary = verify_mod.verify(src, repo_override=args.repo, on_progress=on_progress)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print(f"[FAIL] 溯源失败：{e}")
        return 2

    print("\n" + "=" * 60)
    form = summary.get("form", "Skill")
    if form == "MCP":
        print(f"✅ MCP 形态核实：解析命中 {summary['item_total']} 个 / unresolved {summary.get('unresolved_count', 0)} 个")
        print(f"   安装清单：{summary['install_list']}")
    elif form == "repo":
        print(f"✅ repo 形态核实：待 clone 仓库 {summary['item_total']} 个 / unresolved {summary.get('unresolved_count', 0)} 个")
        print(f"   安装清单：{summary['install_list']}")
    else:
        print(f"✅ 一手核实：{summary['verified_repo']}（⭐{summary['stars']}，{summary['stars_observed_at']}）")
        print(f"   定位方式：{summary['how_resolved']}")
        print(f"   全仓 skill：{summary['skill_total']} 个 → {summary['install_list']}")
    print(f"   plan.json 纠正 {len(summary['corrections'])} 处：")
    for c in summary["corrections"]:
        print(f"     - {c}")
    print("=" * 60)
    print("刹车：到此只核实 + 出安装清单，未安装。安装需另跑 install 并单独授权。")
    return 0


def cmd_dedup(args: argparse.Namespace) -> int:
    """去重：扫本地已装 skill 建基准 → 比 install_list → 判 new/merge/skip（不安装）。"""
    from . import dedup as dedup_mod

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
    print(f"基准：{bc['distinct']} 个 distinct skill（磁盘 {bc['disk_entries']} + 台账 {bc['registry_rows']} 行）")
    print(f"      状态分布：{bc['by_status']}")
    print(f"install_list {s['total']} 项判定：new={s['new']}  merge={s['merge']}  skip={s['skip']}")
    print(f"报告 → {summary['dedup_path']}")
    merges = [d for d in summary["decisions"] if d["decision"] == "merge"]
    if merges:
        print(f"\nmerge 候选（建议人工确认整并，不自动决定）：")
        for d in merges:
            print(f"  - {d['name']} → {d['target']}  [{', '.join(d.get('shared', []))}]")
    print("=" * 60)
    print("刹车：到此只判定 + 出报告，未安装。安装需另跑 install 并单独授权。")
    return 0


def cmd_recommend(args: argparse.Namespace) -> int:
    """判断步（recommend）：去重之后、安装之前，判「值不值得装」（D19 判断先行）。

    读 dedup.json（new/merge/skip 决策）+ install_list.json（候选描述），扫本机能力画像，
    按 --mode 给 new 候选打分/勾选 → 出 recommend.json（approved 名单）。不安装、不改台账。
    keyword/manual 纯本地不烧 token；ai 属积木 D（调文本模型，烧 token，需用户在场，暂未接线）。
    """
    from . import recommend as rec

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
            print("[ERR] ai 模式需文本模型配置（D21 前置），但 .env 缺 base_url/api_key/model 之一。")
            print(f"      text={cfg.text.key_masked}")
            print("      请先补 .env，或改用 --mode keyword（规则打分）/ --mode manual（人工勾选），都不烧 token。")
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
            decisions, profile, descriptions=descriptions, usability=usability_map)
    elif mode == rec.MODE_AI:
        from . import llm
        print(f"   [ai] 烧 token 调文本模型 {cfg.text.model}，分批判断（用户在场监控；--limit={args.limit}）...")
        def _on_batch(i, n, bs, ok):
            tag = "ok" if ok else "FAIL→整批降级「不值得装」"
            print(f"   [ai] 批 {i}/{n}（{bs} 条）→ {tag}")
        new_js = rec.judge_ai(
            decisions, profile, descriptions=descriptions, usability=usability_map,
            cfg=cfg, chat_fn=llm.chat_text, limit=args.limit, on_batch=_on_batch,
        )
    else:  # manual
        new_js = rec.pick_manual(decisions, descriptions=descriptions, usability=usability_map)

    # ---- 合并 skip/merge（trivial 兜底）+ 装配报告 ----
    judgments = rec.merge_judgments(decisions, new_js)
    report = rec.assemble_report(
        decisions, judgments, mode=mode,
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
    print(f"候选汇总：total={sm['total']}  by_verdict={sm['by_verdict']}  approved={sm['approved']}")
    approved = report["approved"]
    shown = approved[:20]
    print(f"approved（install 该装的子集，D20 挑着买）：{shown}{' ...' if len(approved) > 20 else ''}")
    print(f"报告 → {out_path}")
    print("=" * 60)
    print("刹车：判断步只出 recommend.json，未安装。install 只装 approved 子集（须另跑 install --approve）。")
    return 0


def cmd_install(args: argparse.Namespace) -> int:
    """安装：照 dedup 判定的 new skill，整目录拷到运行时默认 Skill 目录，登记台账。"""
    from . import install as install_mod

    cfg = load_config()  # 校验配置 + 路径解析一致（install 不用 LLM，纯 GitHub raw）
    src = _resolve_source(cfg, args.source)
    if not (src / "install_list.json").exists():
        print(f"[ERR] {src} 没有 install_list.json（先跑 verify）")
        return 1
    if not (src / "dedup.json").exists():
        print(f"[ERR] {src} 没有 dedup.json（先跑 dedup）")
        return 1

    mode = "真装" if args.approve else "dry-run（只列计划，不下载不写台账）"
    print(f"[安装] {src}  {mode}")

    def on_progress(s: dict, i: int, n: int) -> None:
        form = s.get("form", "Skill")
        cat = s.get("category", "")
        head = f"{form}/{cat}" if cat else form
        if form == "MCP":
            mcp = s.get("mcp") or {}
            print(f"   [{i + 1}/{n}] 注册 MCP 服务器 {head}/{s['name']}"
                  f"（{mcp.get('transport', 'stdio')} -s {mcp.get('scope', 'user')}）...", flush=True)
        elif form == "repo":
            print(f"   [{i + 1}/{n}] clone {head}/{s['name']}"
                  f"（{s.get('repo', '')}，分支 {s.get('branch', 'main')}）...", flush=True)
        else:
            print(f"   [{i + 1}/{n}] 装 {head}/{s['name']}（整目录拷）...", flush=True)

    # D23：仅 --ai-infer 才注入 chat_fn（DeepSeek），让 install() 对 unresolved MCP 推断装法。
    # 默认关 → install() 纯查表，零行为改变（回归安全）。prompt_fn=None：交互终端走 input()，无终端写进报告。
    chat_fn = (lambda p: llm.chat_text(cfg, p)) if args.ai_infer else None

    try:
        r = install_mod.install(
            src, target_dir=args.target_dir, approve=args.approve,
            include_deprecated=args.include_deprecated, on_progress=on_progress,
            ai_infer=args.ai_infer, no_trial=args.no_trial, refresh_cache=args.refresh_cache,
            chat_fn=chat_fn, prompt_fn=None,
        )
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print(f"[FAIL] 安装失败：{e}")
        return 2

    print("\n" + "=" * 60)
    # per-item 形态明细（反黑箱 D22）：MCP 列 command/args/scope/usability，Skill 列目标+文件数
    detail = r.get("items_detail") or []
    first_form = detail[0].get("form", "Skill") if detail else "Skill"
    if first_form == "repo":
        repo_id = detail[0].get("repo", "") or "(未知)"
        print(f"源视频：{r['source_video']}  repo：{repo_id}")
    elif first_form == "MCP":
        print(f"源视频：{r['source_video']}  形态：MCP（{len(detail)} 个能力）")
    else:
        print(f"源视频：{r['source_video']}  仓库：{r['verified_repo'] or '(未知)'}")
    print(f"目标目录：{r['target_dir']}  安装前 distinct：{r['before']}")
    print(f"将装 new：{len(detail)} 个")
    for it in detail:
        form = it.get("form", "Skill")
        usab = it.get("usability", "ready")
        flag = f" [{usab}]" if usab and usab != "ready" else ""
        if form == "MCP":
            cmd = it.get("command", "")
            argstr = " ".join(it.get("args", []))
            print(f"  - {it['name']}（MCP，{it.get('transport', 'stdio')} -s {it.get('scope', 'user')}，"
                  f"{cmd} {argstr}）{flag}")
        elif form == "repo":
            print(f"  - {it['name']}（repo，clone → {it.get('repo', '')}，"
                  f"分支 {it.get('branch', 'main')}）{flag}")
        else:
            print(f"  - {it['name']}（Skill → {it.get('target', '')}）{flag}")
    if r["skipped_merge"]:
        print(f"跳过 merge（人工确认）：{len(r['skipped_merge'])} 个 → {r['skipped_merge']}")
    if r["skipped_deprecated"]:
        print(f"跳过 deprecated：{len(r['skipped_deprecated'])} 个 → {r['skipped_deprecated']}（--include-deprecated 可装）")
    if r["skipped_already"]:
        print(f"跳过已装/已整并：{len(r['skipped_already'])} 个")
    unresolved = r.get("unresolved") or []
    if unresolved:
        print(f"unresolved（待你拍板，不自动包装）：{len(unresolved)} 个")
        for u in unresolved:
            print(f"  · {u.get('name')}：{u.get('reason')}（候选：{u.get('candidate', '')}）")
    resolve_traces = r.get("resolve_traces") or []
    if resolve_traces:
        print(f"\nAI 推断明细（resolve trace）：{len(resolve_traces)} 条")
        for t in resolve_traces:
            print(f"  · {t}")
    if args.approve:
        installed = r.get("installed", [])
        print(f"\n✅ 已落盘 {len(installed)} 个能力，安装后 distinct：{r.get('after')}")
        for s in installed:
            form = s.get("form", "Skill")
            if form == "MCP":
                usab = s.get("usability", "ready")
                flag = f" [{usab}]" if usab and usab != "ready" else ""
                print(f"  - {s['name']}（MCP，{s.get('registered_via')}，scope={s.get('scope')}，"
                      f"{s.get('transport', 'stdio')}）→ {s.get('path', '')}{flag}")
            elif form == "repo":
                usab = s.get("usability", "ready")
                flag = f" [{usab}]" if usab and usab != "ready" else ""
                cloned = "新克隆" if s.get("cloned_now") else "已存在(幂等跳过)"
                deps = "依赖✅" if s.get("deps_installed") else f"依赖待补({s.get('deps_method', 'none')})"
                print(f"  - {s['name']}（repo，{s.get('repo', '')}@{s.get('branch', 'main')}，"
                      f"{cloned}，{deps}）→ {s.get('path', '')}{flag}")
            else:
                print(f"  - {s['name']}（{s.get('file_count', 0)} 文件）→ {s.get('path', '')}")
        if r.get("skipped_credentials"):
            names = ", ".join(d["name"] for d in r["skipped_credentials"])
            print(f"   跳过需凭证：{len(r['skipped_credentials'])} 个 → {names}（配 credential_env 后重跑）")
        if r.get("skipped_config"):
            names = ", ".join(d["name"] for d in r["skipped_config"])
            print(f"   跳过需配置：{len(r['skipped_config'])} 个 → {names}（替换占位符后重跑）")
        print(f"   {r.get('note', '')}")
        # 邮件通知（可选）：install --approve 真装完成才发 HTML 报告（用户立规，
        # 延续 feedback-install-report-email）。未配置→主动提示一次（不报错）；
        # 配置→发完回执；发送本身失败也不影响安装结果。
        if notify.is_configured():
            res = notify.send_html(
                f"[skillbrew] 安装完成 · {r.get('source_video', '')}",
                notify.install_report_html(r, src),
            )
            if res.get("success"):
                print(f"   📧 已发完成报告邮件 → {res.get('to')}")
            else:
                reason = res.get("error") or res.get("reason") or "未知"
                print(f"   ⚠ 邮件未发出：{reason}")
        else:
            print(f"   💡 {notify.unconfigured_hint()}")
    else:
        print("\n   " + r.get("note", ""))
        print("   加 --approve 才真落盘 + 写台账。")
    print("=" * 60)
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    """记录+看板：从台账/清单/去重一手数据代码生成安装记录与看板（只读，不改台账）。"""
    from . import record as record_mod

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
    print(f"   落盘核对：磁盘 {ig['disk_active_distinct']} == 台账 {ig['registry_active']}"
          f" → {'✅一致' if ig['ok'] else '⚠️不一致'}")
    if ig["orphans"]:
        print(f"   孤儿（磁盘有/台账无）：{ig['orphans']}")
    if ig["missing"]:
        print(f"   缺失（台账有/磁盘无）：{ig['missing']}")
    print(f"   记录 → {r['record_path']}")
    print(f"   看板 → {r['dashboard_path']}")
    print("=" * 60)
    print("刹车：record 只读，未改台账、未下载、未调 LLM。")
    return 0


def main(argv: list[str] | None = None) -> int:
    # 入口统一 UTF-8：Windows 默认 GBK 控制台 print 含 ​（零宽空格）等字符会崩
    # 在最后一刻（明明下载成功却因打日志崩，issue #5）。统一 UTF-8+errors=replace，
    # 所有 print 都不会因编码炸。库式调用（import 后调函数）不受影响。
    ensure_utf8_stdout()
    parser = argparse.ArgumentParser(
        prog="skillbrew",
        description="AI 能力包管理器：素材 → 消化 → 计划 → 授权安装 → 能力台账",
    )
    parser.add_argument("--version", action="version", version=f"skillbrew {__version__}")
    parser.add_argument(
        "--runtime", choices=["claude", "codex"], default=None,
        help="显式指定 agent 运行时（默认自动探测：CODEX_HOME 或 ~/.codex 存在则 codex，否则 claude）",
    )
    parser.add_argument(
        "--clones-dir", default=None, metavar="DIR",
        help="覆盖默认 clone 落地目录（env SKILLBREW_CLONES_DIR 优先级更高）",
    )
    parser.add_argument(
        "--mcp-json", default=None, metavar="PATH",
        help="覆盖默认 MCP 配置文件路径（env SKILLBREW_CLAUDE_JSON 优先级更高）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doc = sub.add_parser("doctor", help="自检：配置 + 文本/视觉连通性")
    p_doc.add_argument(
        "--vision", action="store_true", help="额外跑一次真·看图实测（Agnes ~5min/张）"
    )
    p_doc.set_defaults(func=cmd_doctor)

    p_cfg = sub.add_parser("config", help="打印解析后的配置（key 脱敏）")
    p_cfg.set_defaults(func=cmd_config)

    p_run = sub.add_parser("run", help="一键：采集→理解→消化→草稿计划（到此为止，不安装）")
    p_run.add_argument("source", help="B站 URL 或 BV 号")
    p_run.add_argument("--qn", type=int, default=32, help="清晰度 16/32/64/80")
    p_run.add_argument("--max-frames", type=int, default=5, help="关键帧数")
    p_run.add_argument("--max-workers", type=int, default=3, help="视觉并发数")
    p_run.add_argument("--skip-asr", action="store_true", help="跳过字幕转写")
    p_run.add_argument("--skip-vision", action="store_true", help="跳过视觉看图（省时，纯字幕消化）")
    p_run.add_argument("--force", action="store_true", help="不跳过已有产物，重跑")
    p_run.set_defaults(func=cmd_run)

    p_ing = sub.add_parser("ingest", help="只跑采集（下载视频 + 音频）")
    p_ing.add_argument("source", help="B站 URL 或 BV 号")
    p_ing.add_argument("--qn", type=int, default=32)
    p_ing.set_defaults(func=cmd_ingest)

    p_und = sub.add_parser("understand", help="只跑理解（字幕 + 关键帧 + 视觉）")
    p_und.add_argument("source", help="源目录 或 B站URL/BV号")
    p_und.add_argument("--max-frames", type=int, default=5)
    p_und.add_argument("--max-workers", type=int, default=3)
    p_und.add_argument("--skip-asr", action="store_true")
    p_und.add_argument("--skip-vision", action="store_true")
    p_und.add_argument("--force", action="store_true")
    p_und.set_defaults(func=cmd_understand)

    p_plan = sub.add_parser("plan", help="只跑消化（字幕 + 视觉 → 草稿计划）")
    p_plan.add_argument("source", help="源目录 或 B站URL/BV号")
    p_plan.set_defaults(func=cmd_plan)

    p_ver = sub.add_parser("verify", help="溯源：回 GitHub 取一手资料，纠正草稿计划 + 出机器安装清单")
    p_ver.add_argument("source", help="源目录 或 B站URL/BV号")
    p_ver.add_argument("--repo", default=None, help="手动指定 owner/repo（绕过自动搜索）")
    p_ver.set_defaults(func=cmd_verify)

    p_ded = sub.add_parser("dedup", help="去重：扫本地已装 skill 建基准，比 install_list，判 new/merge/skip")
    p_ded.add_argument("source", help="源目录 或 B站URL/BV号")
    p_ded.add_argument(
        "--skills-dir", action="append", default=None, metavar="DIR",
        help="追加要扫描的 Skill 目录（可重复；默认已含运行时默认 Skill 目录）",
    )
    p_ded.set_defaults(func=cmd_dedup)

    p_rec_judge = sub.add_parser(
        "recommend",
        help="判断步：去重后判「值不值得装」，出 recommend.json（不安装；keyword/manual 不烧 token）",
    )
    p_rec_judge.add_argument("source", help="源目录 或 B站URL/BV号")
    p_rec_judge.add_argument(
        "--skills-dir", action="append", default=None, metavar="DIR",
        help="追加扫描目录（默认已含运行时默认 Skill 目录，与去重同口径）",
    )
    p_rec_judge.add_argument(
        "--mode", choices=["keyword", "manual", "ai"], default="keyword",
        help="判断模式：keyword=规则打分(默认,无 key) / manual=人工勾选(无 key) / ai=文本模型(烧 token,需在场)",
    )
    p_rec_judge.add_argument(
        "--source-skip", default=None, metavar="REASON",
        help="整源跳过：手判该源非技能集（如配置商店）否决整源，approved 置空（D19 人定）",
    )
    p_rec_judge.add_argument(
        "--limit", type=int, default=None, metavar="N",
        help="ai 模式成本控制：只判前 N 条 new 候选（未判到的由 merge 兜底「不值得装」）",
    )
    p_rec_judge.set_defaults(func=cmd_recommend)

    p_inst = sub.add_parser(
        "install", help="安装：照 dedup 判定的 new skill，整目录拷到运行时默认 Skill 目录并登记台账",
    )
    p_inst.add_argument("source", help="源目录 或 B站URL/BV号")
    p_inst.add_argument("--approve", action="store_true", help="真落盘 + 写台账（默认 dry-run，只列计划）")
    p_inst.add_argument(
        "--include-deprecated", action="store_true", help="连 deprecated skill 一起装（默认跳过）",
    )
    p_inst.add_argument("--target-dir", default=None, help="安装目标目录（默认运行时默认 Skill 目录）")
    p_inst.add_argument(
        "--ai-infer", action="store_true",
        help="对 verify 标 unresolved 的 MCP，开 AI 读源头仓库推断装法+试跑验证+缺项补全（D23，默认关）",
    )
    p_inst.add_argument(
        "--no-trial", action="store_true",
        help="跳过装前试跑（推断后不验证直接装，未验证不入缓存）",
    )
    p_inst.add_argument(
        "--refresh-cache", action="store_true",
        help="忽略本地缓存重新推断装法（强刷已缓存的装法）",
    )
    p_inst.set_defaults(func=cmd_install)

    p_rec = sub.add_parser(
        "record",
        help="记录+看板：从台账/清单/去重一手数据代码生成安装记录与看板（只读，不改台账）",
    )
    p_rec.add_argument("source", help="源目录 或 B站URL/BV号")
    p_rec.add_argument(
        "--skills-dir", action="append", default=None, metavar="DIR",
        help="追加扫描目录（默认读 dedup.json 的 baseline.skill_dirs，与去重同口径）",
    )
    p_rec.set_defaults(func=cmd_record)

    args = parser.parse_args(argv)

    # CLI 全局标志透传为环境变量，确保 config.detect_runtime()/skills_dir()/claude_json_path()
    # /repo_clones_dir() 在本进程内即时生效（env 优先级高于运行时默认）。
    if args.runtime:
        os.environ.setdefault("SKILLBREW_RUNTIME", args.runtime)
    if args.clones_dir:
        os.environ.setdefault("SKILLBREW_CLONES_DIR", args.clones_dir)
    if args.mcp_json:
        os.environ.setdefault("SKILLBREW_CLAUDE_JSON", args.mcp_json)

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
