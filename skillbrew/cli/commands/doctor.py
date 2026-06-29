"""`doctor` 子命令：自检配置与模型连通性。"""

from __future__ import annotations

import argparse
import os
import tempfile
import time
import traceback

from skillbrew import __version__, llm
from skillbrew.config import load_config

from ..utils import _check_present, _make_half_half_png, _print_config


def cmd_doctor(args: argparse.Namespace) -> int:
    print(f"skillbrew {__version__} 自检")
    print("=" * 60)
    cfg = load_config()
    _print_config(cfg)
    print("-" * 60)
    text_ok = _check_present(cfg)

    # ---- 判断步 recommend 可用性（D21：无 key 不走死路，keyword/manual 恒可用）----
    from skillbrew import recommend

    print("\n[判断步 recommend] 三模式可用性：")
    for line in recommend.recommend_health(cfg):
        print("   -", line)

    if not text_ok:
        print(
            "\n[FAIL] 文本模型必备（D21）。keyword/manual 判断步仍可用；请检查 .env（参考 .env.example）。"
        )
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
        reply = llm.chat_text(cfg, "用一句话介绍你自己，并说出你的模型名。", timeout=60)
        print(f"   [OK] {time.time() - t0:.1f}s -> {reply}")
    except Exception as e:
        from skillbrew.errors import SkillbrewError

        if isinstance(e, SkillbrewError):
            print(f"   [WARN] {e}")
            if e.hint:
                print(f"   → {e.hint}")
        else:
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
