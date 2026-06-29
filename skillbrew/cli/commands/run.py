"""`run` 子命令：一键采集→理解→消化→草稿计划。"""

from __future__ import annotations

import argparse
import json

from skillbrew.config import load_config

from ..utils import _print_progress, _spinner


def cmd_run(args: argparse.Namespace) -> int:
    """一键：采集 → 理解(字幕+关键帧+视觉) → 消化 → 草稿计划，到此为止不安装。"""
    from skillbrew import ingest, plan, understand

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
        with _spinner("[①采集] 下载视频+音频"):
            r = ingest.fetch_bilibili(args.source, src_dir, qn=args.qn)
        print(f"   -> {r.title}（时长 {r.duration}s）")

    # ② 字幕 ASR
    _empty_transcript = '{"segments":[],"text":"","language":""}'
    if args.skip_asr:
        print("[②字幕] --skip-asr 跳过")
        _tp = src_dir / "transcript.json"
        if not _tp.exists():
            _tp.write_text(_empty_transcript, encoding="utf-8")
            (src_dir / "transcript.txt").write_text("", encoding="utf-8")
        _tp = src_dir / "transcript.json"
        if not _tp.exists():
            _tp.write_text(_empty_transcript, encoding="utf-8")
            (src_dir / "transcript.txt").write_text("", encoding="utf-8")
    elif not args.force and (src_dir / "transcript.json").exists():
        print("[②字幕] 已存在，跳过")
    else:
        with _spinner("[②字幕] ASR 转写（首次加载模型~160s）"):
            t = understand.transcribe(src_dir / "audio.mp3", src_dir)
        print(f"   -> {len(t['segments'])} 段, {len(t['text'])} 字")

    # ③ 关键帧
    if not args.force and (src_dir / "keyframes_align.json").exists():
        print("[③关键帧] 已存在，跳过")
    else:
        with _spinner(f"[③关键帧] farthest-point 采样 {args.max_frames} 帧"):
            kfs = understand.select_keyframes(
                src_dir / "video.mp4", src_dir, max_frames=args.max_frames
            )
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
        print(f"[④视觉] 看关键帧（并发 {args.max_workers}，Agnes ~5min/张，请耐心）...")

        def _on_vprog(r: dict, done: int, total: int) -> None:
            tag = "ok" if r.get("ok") else "fail"
            elapsed = r.get("elapsed", 0)
            _print_progress(done, total, label=f"{r.get('file', '')} {tag} {elapsed}s")

        with _spinner(f"[④视觉] 看关键帧（并发 {args.max_workers}）"):
            res = understand.describe_keyframes(
                cfg, src_dir, max_workers=args.max_workers, on_progress=_on_vprog
            )
        ok = sum(1 for r in res if r["ok"])
        print(f"   -> {ok}/{len(res)} 张成功")
        if ok < len(res):
            print("   ⚠️ 部分帧失败，草稿计划将只基于成功的视觉描述 + 字幕")

    # ⑤ 消化 → 草稿计划
    if not args.force and (src_dir / "plan.json").exists():
        print("[⑤消化] 计划已存在，跳过（--force 可重跑）")
    else:
        with _spinner("[⑤消化] DeepSeek 融合字幕+视觉→计划"):
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
