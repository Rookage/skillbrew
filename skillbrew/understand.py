"""understand：视频理解 = ASR 字幕 + 关键帧抽取 + 时间轴对齐。

- ASR：faster-whisper(small/int8/CPU/vad_filter，中文)。模型走 hf-mirror.com 镜像
  避免下载 hang 死。无字幕视频靠它把语音转成带时间戳的文本。
- 关键帧：**ffmpeg 的 `scene` 检测在本类短视频上实测失效**（全程场景分 <0.02），
  改用 PIL 帧间差异 + farthest-point 采样：等距抽缩略图 → 算灰度签名 → 贪心选
  互相差异最大的 N 帧（限帧策略 A），保证视觉覆盖多样。
- 对齐：每帧 ±窗口内的字幕文本，供后续消化把"画面+同期语音"一起喂 LLM。
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

_THUMB_W, _THUMB_H = 32, 24  # 签名缩略图尺寸

_VISION_PROMPT = (
    "这是一段科技短视频里的一帧画面。请用中文简洁描述：画面里出现了什么？"
    "重点指出画面中的文字、代码、网址(URL)、软件界面(UI)、GitHub 页面、幻灯片或图表内容；"
    "如果是人物口播画面也请说明。3-5 句话以内。"
)


def transcribe(audio_path: Path, out_dir: Path, *, model_size: str = "small") -> dict:
    """faster-whisper ASR。返回 {text, segments}，并落 transcript.json/.txt。"""
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
    os.environ.setdefault("HF_HUB_ENDPOINT", "https://hf-mirror.com")
    from faster_whisper import WhisperModel  # 懒导入（可选依赖）

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    m = WhisperModel(model_size, device="cpu", compute_type="int8")
    segs, info = m.transcribe(str(audio_path), language="zh", vad_filter=True, beam_size=5)
    seg_list = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]
    full = "".join(s["text"] for s in seg_list)
    (out_dir / "transcript.json").write_text(
        json.dumps({"segments": seg_list, "text": full, "language": info.language}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "transcript.txt").write_text(full, encoding="utf-8")
    return {"segments": seg_list, "text": full}


def _signatures(video_path: Path, interval: float) -> list[tuple[float, np.ndarray]]:
    """等距抽缩略图(灰度 32x24)，返回 [(时间秒, 签名向量)]。"""
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video_path), "-vf", f"fps=1/{interval},scale={_THUMB_W}:{_THUMB_H},format=gray",
            str(td / "s_%04d.jpg"),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        sigs = []
        for p in sorted(td.glob("s_*.jpg")):
            t = (int(p.stem.split("_")[1]) - 1) * interval
            arr = np.asarray(Image.open(p).convert("L"), dtype=np.float32)
            sigs.append((round(t, 1), arr))
    return sigs


def select_keyframes(
    video_path: Path,
    out_dir: Path,
    *,
    max_frames: int = 5,
    interval: float = 2.0,
    min_spacing: float = 5.0,
) -> list[dict]:
    """选 N 张互相差异最大的关键帧并全分辨率抽出。返回 [{t, file}]。

    farthest-point 采样：先纳入首帧，之后每轮选离已选集合"最近距离最大"的帧
    （即最能补全新视角的帧），并强制 min_spacing 避免扎堆。
    """
    out_dir = Path(out_dir)
    kf_dir = out_dir / "keyframes"
    kf_dir.mkdir(parents=True, exist_ok=True)
    for old in kf_dir.glob("kf_*.jpg"):
        old.unlink()

    sigs = _signatures(video_path, interval)
    if not sigs:
        raise RuntimeError("抽帧为空，检查视频文件")

    # farthest-point 采样
    chosen_idx = [0]
    while len(chosen_idx) < min(max_frames, len(sigs)):
        best_i, best_d = -1, -1.0
        for i, (_, sig) in enumerate(sigs):
            if i in chosen_idx:
                continue
            # 与已选最近距离
            d_min = min(float(np.mean(np.abs(sig - sigs[j][1]))) for j in chosen_idx)
            # 强制最小间距：与已选时间太近的不选
            if any(abs(sigs[i][0] - sigs[j][0]) < min_spacing for j in chosen_idx):
                continue
            if d_min > best_d:
                best_d, best_i = d_min, i
        if best_i < 0:  # 受 min_spacing 限制无候选，放宽
            remaining = [i for i in range(len(sigs)) if i not in chosen_idx]
            if not remaining:
                break
            best_i = max(remaining, key=lambda i: min(
                float(np.mean(np.abs(sigs[i][1] - sigs[j][1]))) for j in chosen_idx))
        chosen_idx.append(best_i)
    chosen_idx.sort(key=lambda i: sigs[i][0])

    # 全分辨率抽出选中帧
    result = []
    for i in chosen_idx:
        t = sigs[i][0]
        kf_path = kf_dir / f"kf_{int(t)}s.jpg"
        subprocess.run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", str(t), "-i", str(video_path), "-frames:v", "1", "-q:v", "2", str(kf_path),
        ], check=True, capture_output=True, text=True)
        result.append({"t": t, "file": kf_path.name, "path": str(kf_path)})
    return result


def align_keyframes(transcript_path: Path, keyframes: list[dict], *, window: float = 5.0) -> list[dict]:
    """每帧 ±window 秒内的字幕文本，返回 [{t, file, nearby_subtitle}]。"""
    data = json.loads(Path(transcript_path).read_text(encoding="utf-8"))
    segs = data["segments"] if isinstance(data, dict) and "segments" in data else data
    aligned = []
    for kf in keyframes:
        t = kf["t"]
        near = "".join(s["text"].strip() for s in segs if t - window <= s["start"] <= t + window)
        aligned.append({"t": t, "file": kf["file"], "nearby_subtitle": near})
    return aligned


def describe_keyframes(
    cfg,
    source_dir: Path,
    *,
    max_workers: int = 3,
    prompt: str | None = None,
    timeout: float = 900.0,
) -> list[dict]:
    """批量看关键帧（视觉，Agnes ~5min/张），落 keyframe_visions.json。

    把 keyframes/kf_*.jpg 逐张送视觉模型，问"画面里有什么"，结构化存盘。
    并发(max_workers) + 每帧最多重试 2 次（应对排队/偶发错误）。返回
    [{t,file,ok,desc,elapsed,...}]。收编自原 scripts/vision_keyframes.py，
    使 understand 模块自带视觉批处理，不再依赖外部脚本。
    """
    import time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from . import llm

    src_dir = Path(source_dir)
    kfs = sorted(
        src_dir.glob("keyframes/kf_*.jpg"),
        key=lambda p: int(p.stem.split("_")[1].rstrip("s")),
    )
    if not kfs:
        raise RuntimeError(f"没找到关键帧: {src_dir / 'keyframes' / 'kf_*.jpg'}")

    p = prompt or _VISION_PROMPT

    def _one(kf_path: Path) -> dict:
        t_sec = int(kf_path.stem.split("_")[1].rstrip("s"))
        t0 = time.time()
        last_err = ""
        for attempt in range(3):  # 最多重试 2 次
            try:
                desc = llm.chat_vision(cfg, p, kf_path, timeout=timeout)
                return {
                    "t": t_sec, "file": kf_path.name, "ok": True,
                    "desc": desc, "elapsed": round(time.time() - t0, 1),
                    "attempts": attempt + 1,
                }
            except Exception as e:  # noqa: BLE001
                last_err = f"{type(e).__name__}: {str(e)[:200]}"
                time.sleep(5 * (attempt + 1))
        return {
            "t": t_sec, "file": kf_path.name, "ok": False, "desc": "",
            "elapsed": round(time.time() - t0, 1), "error": last_err,
            "attempts": 3,
        }

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_one, kf): kf for kf in kfs}
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda x: x["t"])
    (src_dir / "keyframe_visions.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return results


# ---- 直接运行：对已获取的源做 ASR + 关键帧 + 对齐 ----
def _main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m skillbrew.understand <源目录> [--skip-asr]")
        print("     源目录需含 video.mp4 + audio.mp3（先跑 ingest）")
        return 1
    src = Path(sys.argv[1])
    skip_asr = "--skip-asr" in sys.argv
    if not skip_asr and (src / "audio.mp3").exists():
        print(f"[ASR] {src/'audio.mp3'}（首次加载模型~160s）...")
        t = transcribe(src / "audio.mp3", src)
        print(f"  -> {len(t['segments'])} 段, {len(t['text'])} 字")
    print("[关键帧] farthest-point 采样 5 帧...")
    kfs = select_keyframes(src / "video.mp4", src, max_frames=5)
    align = align_keyframes(src / "transcript.json", kfs)
    (src / "keyframes_align.json").write_text(json.dumps(align, ensure_ascii=False, indent=2), encoding="utf-8")
    for a in align:
        print(f"  t={a['t']}s  字幕: {a['nearby_subtitle'][:60]}")
    print(f"[OK] 关键帧 {len(kfs)} 张 → {src/'keyframes'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
