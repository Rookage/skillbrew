"""`run` 子命令：一键采集→理解→消化→草稿计划（多源版，P3-1）。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from skillbrew.config import load_config
from skillbrew.sources import (
    detect_adapter,
    fetch_with_adapter,
    is_video_source,
    resolve_subdir,
    source_type,
)

from ..utils import _print_progress, _spinner


def _do_fetch(src: str, src_dir: Path, is_video: bool, stype: str, qn: int, force: bool) -> object:
    """统一采集步骤。视频需要 video.mp4+audio.mp3，文本只需要 transcript.txt。"""
    have_video = (src_dir / "video.mp4").exists() and (src_dir / "audio.mp3").exists()
    have_text = (src_dir / "transcript.txt").exists()
    if not force and ((is_video and have_video) or (not is_video and have_text)):
        print("[①采集] 已存在，跳过")
        # 返回 None 让调用方知道没拿到新结果对象
        return None
    label = "下载视频+音频" if is_video else "抓取文本/网页"
    with _spinner(f"[①采集] {label}"):
        kwargs: dict = {}
        if stype == "bilibili":
            kwargs["qn"] = qn
        r, _cls = fetch_with_adapter(src, src_dir, **kwargs)
    if is_video:
        print(f"   -> {getattr(r, 'title', '')}（时长 {getattr(r, 'duration', 0)}s）")
    else:
        print(f"   -> {getattr(r, 'title', '')}（{len(getattr(r, 'text', ''))} 字）")
    return r


def cmd_run(args: argparse.Namespace) -> int:
    """一键：采集 → 理解(字幕+关键帧+视觉，仅视频) → 消化 → 草稿计划，到此为止不安装。"""
    from skillbrew import plan, understand

    cfg = load_config()
    src = args.source

    cls = detect_adapter(src)
    if cls is None:
        print(f"[FAIL] 无法识别源类型: {src!r}")
        return 2
    stype = source_type(src)
    video = is_video_source(src)
    sub = resolve_subdir(src)
    src_dir = cfg.data_dir / "sources" / sub
    src_dir.mkdir(parents=True, exist_ok=True)
    print(f"源类型={stype}  目录: {src_dir}")

    # ① 采集
    _do_fetch(src, src_dir, video, stype, args.qn, args.force)

    if video:
        # ② 字幕 ASR（视频源：优先用 yt-dlp 下的自动字幕，缺再跑 ASR）
        _empty_transcript = '{"segments":[],"text":"","language":""}'
        if args.skip_asr:
            print("[②字幕] --skip-asr 跳过")
            _tp = src_dir / "transcript.json"
            if not _tp.exists():
                _tp.write_text(_empty_transcript, encoding="utf-8")
                (src_dir / "transcript.txt").write_text("", encoding="utf-8")
        # YouTube 有自动字幕 (.vtt) 时不跑 ASR，understand 模块自己识别；这里只做 ASR 启动门控
        elif not args.force and (src_dir / "transcript.json").exists():
            print("[②字幕] 已存在，跳过")
        else:
            # 如果已存在 .vtt 自动字幕（yt-dlp 下的），走 understand 里的字幕解析而不跑 ASR
            # 这里保持原逻辑：调用 transcribe 让它自己决定（现有 understand.transcribe 暂不处理 .vtt，
            # 未来版本再补；P3-1 不改业务行为）。
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
            print(
                f"[④视觉] 看关键帧（并发 {args.max_workers}，Agnes ~5min/张，请耐心）..."
            )

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
    else:
        # 文本/网页源：跳过 ASR/关键帧/视觉，直接以 transcript.txt 为输入。
        # 但 plan.digest 要求 transcript.txt 非空；确保它存在（采集步已经写好）。
        if not (src_dir / "transcript.txt").exists():
            # 兜底（理论上 fetch_text/fetch_webpage 已写）
            (src_dir / "transcript.txt").write_text("", encoding="utf-8")
        print("[②③④字幕/关键帧/视觉] 文本/网页源，跳过视频理解步骤")

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
