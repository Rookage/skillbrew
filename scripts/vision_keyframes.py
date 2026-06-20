"""批量关键帧视觉理解（MVP · 限帧策略 A+B 实测）。

把 data/sources/<id>/keyframes/*.jpg 逐张送 Agnes 视觉(agnes-1.5-flash)，
问"画面里有什么"(文字/代码/URL/UI/GitHub 内容)，结构化存 keyframe_visions.json。

- 限帧策略 A：只送已选定的 3–8 张关键帧（非几十张）。
- 限帧策略 B：并发请求（max_workers 可调），顺带实测 Agnes 并发是否被限速。
  失败的帧自动重试 2 次（应对排队/偶发错误）。

用法： python scripts/vision_keyframes.py <source_id> [max_workers]
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skillbrew.config import load_config
from skillbrew import llm

PROMPT = (
    "这是一段科技短视频里的一帧画面。请用中文简洁描述：画面里出现了什么？"
    "重点指出画面中的文字、代码、网址(URL)、软件界面(UI)、GitHub 页面、幻灯片或图表内容；"
    "如果是人物口播画面也请说明。3-5 句话以内。"
)


def describe_one(cfg, kf_path: Path) -> dict:
    """看一张关键帧，返回 {t, file, ok, desc, elapsed, error}。"""
    t_sec = int(kf_path.stem.split("_")[1].rstrip("s"))
    t0 = time.time()
    last_err = ""
    for attempt in range(3):  # 最多重试 2 次
        try:
            desc = llm.chat_vision(cfg, PROMPT, kf_path, timeout=900.0)
            return {
                "t": t_sec,
                "file": kf_path.name,
                "ok": True,
                "desc": desc,
                "elapsed": round(time.time() - t0, 1),
                "attempts": attempt + 1,
            }
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {str(e)[:200]}"
            time.sleep(5 * (attempt + 1))
    return {
        "t": t_sec,
        "file": kf_path.name,
        "ok": False,
        "desc": "",
        "elapsed": round(time.time() - t0, 1),
        "error": last_err,
        "attempts": 3,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python scripts/vision_keyframes.py <source_id> [max_workers]")
        return 1
    source_id = sys.argv[1]
    max_workers = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    cfg = load_config()
    src_dir = cfg.data_dir / "sources" / source_id
    kfs = sorted(src_dir.glob("keyframes/kf_*.jpg"), key=lambda p: int(p.stem.split("_")[1].rstrip("s")))
    if not kfs:
        print(f"[ERR] 没找到关键帧: {src_dir}/keyframes/kf_*.jpg")
        return 1

    print(f"开始视觉理解 {len(kfs)} 张关键帧，并发 {max_workers}（Agnes ~5min/张，请耐心）...")
    for kf in kfs:
        print(f"  - {kf.name}")

    results = []
    done = 0
    t_all = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(describe_one, cfg, kf): kf for kf in kfs}
        for fut in as_completed(futures):
            r = fut.result()
            done += 1
            tag = "OK " if r["ok"] else "FAIL"
            print(f"  [{done}/{len(kfs)}] {tag} {r['file']}  {r['elapsed']}s  尝试{r.get('attempts',1)}次", flush=True)
            if r["ok"]:
                print(f"        -> {r['desc'][:160]}", flush=True)
            else:
                print(f"        -> 错误: {r.get('error','')}", flush=True)
            results.append(r)

    results.sort(key=lambda x: x["t"])
    out = src_dir / "keyframe_visions.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for r in results if r["ok"])
    print(f"\n完成：{ok}/{len(results)} 张成功，总耗时 {time.time()-t_all:.0f}s，结果存 {out}")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
