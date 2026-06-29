"""`understand` 子命令：只跑理解（字幕 + 关键帧 + 视觉）。"""

from __future__ import annotations

import argparse
import json

from skillbrew.config import load_config

from ..utils import _resolve_source


def cmd_understand(args: argparse.Namespace) -> int:
    """只跑理解（字幕 + 关键帧 + 视觉）。"""
    from skillbrew import understand

    cfg = load_config()
    src = _resolve_source(cfg, args.source)
    if not (src / "video.mp4").exists():
        print(f"[ERR] {src} 没有 video.mp4（先跑 ingest）")
        return 1

    if args.skip_asr:
        print("[字幕] --skip-asr 跳过")
        if not (src / "transcript.json").exists():
            _empty = '{"segments":[],"text":"","language":""}'
            (src / "transcript.json").write_text(_empty, encoding="utf-8")
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
