"""understand 核心路径补测（离线 mock，不跑 ffmpeg/whisper/LLM）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ---------- align_keyframes 纯逻辑 ----------


def test_align_keyframes_basic(tmp_path):
    """基本对齐：每帧在 ±window 内抓字幕片段。"""
    from skillbrew.understand import align_keyframes

    tr = {
        "segments": [
            {"start": 0.0, "end": 3.0, "text": "开场白"},
            {"start": 4.0, "end": 8.0, "text": "核心观点"},
            {"start": 10.0, "end": 14.0, "text": "结尾演示"},
        ]
    }
    tp = tmp_path / "transcript.json"
    tp.write_text(json.dumps(tr, ensure_ascii=False), encoding="utf-8")

    kfs = [{"t": 2.0, "file": "kf_2s.jpg"}, {"t": 12.0, "file": "kf_12s.jpg"}]
    out = align_keyframes(tp, kfs, window=5.0)
    assert len(out) == 2
    assert "开场白" in out[0]["nearby_subtitle"]
    assert "核心观点" in out[0]["nearby_subtitle"]
    assert "结尾演示" in out[1]["nearby_subtitle"]
    assert out[0]["t"] == 2.0
    assert out[1]["file"] == "kf_12s.jpg"


def test_align_keyframes_empty_transcript(tmp_path):
    """空字幕：nearby_subtitle 为空串但不报错。"""
    from skillbrew.understand import align_keyframes

    tp = tmp_path / "transcript.json"
    tp.write_text(json.dumps({"segments": []}), encoding="utf-8")
    out = align_keyframes(tp, [{"t": 5.0, "file": "k.jpg"}], window=5.0)
    assert out[0]["nearby_subtitle"] == ""


def test_align_keyframes_accepts_list_format(tmp_path):
    """transcript.json 若直接存 list（旧格式）也能读。"""
    from skillbrew.understand import align_keyframes

    tp = tmp_path / "transcript.json"
    tp.write_text(
        json.dumps([{"start": 0, "end": 2, "text": "hi"}], ensure_ascii=False),
        encoding="utf-8",
    )
    out = align_keyframes(tp, [{"t": 1, "file": "k.jpg"}], window=3.0)
    assert "hi" in out[0]["nearby_subtitle"]


# ---------- _warn_asr_unavailable 纯打印 ----------


def test_warn_asr_unavailable_with_local_path(capsys):
    """设了 WHISPER_MODEL_PATH 时提醒查本地目录。"""
    from skillbrew.understand import _warn_asr_unavailable

    _warn_asr_unavailable("small", "/tmp/m", RuntimeError("boom"))
    out = capsys.readouterr().err
    assert "ASR" in out
    assert "WHISPER_MODEL_PATH" in out
    assert "检查目录是否完整" in out


def test_warn_asr_unavailable_without_local_path(capsys):
    """无本地路径时提醒镜像/hf。"""
    from skillbrew.understand import _warn_asr_unavailable

    _warn_asr_unavailable("small", "", RuntimeError("boom"))
    out = capsys.readouterr().err
    assert "hf-mirror.com" in out
    assert "没字幕也能继续" in out


# ---------- transcribe 降级路径 ----------


def test_transcribe_failure_writes_empty(tmp_path, monkeypatch):
    """WhisperModel 加载/转写失败：不抛，落盘空 transcript，返回空。"""
    from skillbrew import understand

    class _BoomModel:
        def __init__(self, *a, **kw):
            raise RuntimeError("download hang")

    monkeypatch.setattr(
        understand,
        "WhisperModel",
        _BoomModel,
        raising=False,
    )

    import types

    fake_mod = types.ModuleType("faster_whisper")
    fake_mod.WhisperModel = _BoomModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_mod)

    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"fake")
    res = understand.transcribe(audio, tmp_path)
    assert res == {"segments": [], "text": ""}
    assert (tmp_path / "transcript.json").exists()
    assert (tmp_path / "transcript.txt").exists()
    data = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    assert data["segments"] == []
    assert data["text"] == ""


# ---------- describe_keyframes 异常/重试 ----------


def test_describe_keyframes_raises_when_no_kfs(tmp_path):
    """没有关键帧文件时抛 RuntimeError。"""
    import pytest

    import skillbrew.understand as ud

    (tmp_path / "keyframes").mkdir(parents=True, exist_ok=True)
    with pytest.raises(RuntimeError, match="没找到关键帧"):
        ud.describe_keyframes(object(), tmp_path, max_workers=1)


def test_describe_keyframes_partial_failure(monkeypatch, tmp_path):
    """2 帧里 1 帧视觉失败：返回 ok=False 的 dict，不影响其它，落盘。"""
    import time as time_mod

    import skillbrew.llm as llm_mod
    import skillbrew.understand as ud

    kf_dir = tmp_path / "keyframes"
    kf_dir.mkdir()
    for t in (0, 10):
        (kf_dir / f"kf_{t}s.jpg").write_bytes(b"fake")

    calls = {"n": 0}

    def _fake_chat_vision(cfg, prompt, img_path, timeout=900.0):
        calls["n"] += 1
        if "kf_0s" in str(img_path):
            return "ok frame 0"
        raise RuntimeError("vision api down")

    monkeypatch.setattr(llm_mod, "chat_vision", _fake_chat_vision)
    monkeypatch.setattr(time_mod, "sleep", lambda *_a, **_kw: None)

    res = ud.describe_keyframes(object(), tmp_path, max_workers=1)
    assert len(res) == 2
    by_t = {r["t"]: r for r in res}
    assert by_t[0]["ok"] is True
    assert by_t[0]["desc"] == "ok frame 0"
    assert by_t[10]["ok"] is False
    assert "error" in by_t[10]
    assert by_t[10]["attempts"] == 3
    data = json.loads((tmp_path / "keyframe_visions.json").read_text(encoding="utf-8"))
    assert len(data) == 2
    assert sum(1 for r in data if r["ok"]) == 1


def test_describe_keyframes_retries_then_succeeds(monkeypatch, tmp_path):
    """前 2 次失败第 3 次成功：ok=True，attempts=3。"""
    import time as time_mod

    import skillbrew.llm as llm_mod
    import skillbrew.understand as ud

    kf_dir = tmp_path / "keyframes"
    kf_dir.mkdir()
    (kf_dir / "kf_5s.jpg").write_bytes(b"fake")

    state = {"n": 0}

    def _fake_chat_vision(cfg, prompt, img_path, timeout=900.0):
        state["n"] += 1
        if state["n"] < 3:
            raise RuntimeError("retry me")
        return "finally ok"

    monkeypatch.setattr(llm_mod, "chat_vision", _fake_chat_vision)
    monkeypatch.setattr(time_mod, "sleep", lambda *_a, **_kw: None)

    res = ud.describe_keyframes(object(), tmp_path, max_workers=1)
    assert len(res) == 1
    assert res[0]["ok"] is True
    assert res[0]["attempts"] == 3
    assert res[0]["desc"] == "finally ok"


# ---------- select_keyframes：mock ffmpeg 和 _signatures ----------

_THUMB_W_TEST = 32
_THUMB_H_TEST = 24


def test_select_keyframes_uses_farthest_point(monkeypatch, tmp_path):
    """farthest-point 采样：伪造签名差异，验证至少选到 N 帧并写到 keyframes/。"""
    import numpy as np

    import skillbrew.understand as ud

    sigs = []
    for i in range(6):
        arr = np.zeros((_THUMB_H_TEST, _THUMB_W_TEST), dtype=np.float32)
        arr[:, : i + 1] = 255
        sigs.append((float(i * 2), arr))

    monkeypatch.setattr(ud, "_signatures", lambda _v, _i: sigs)

    def _fake_run(cmd, **kw):
        out_path = cmd[-1]
        Path(out_path).write_bytes(b"fakejpg")
        return None

    import subprocess

    monkeypatch.setattr(subprocess, "run", _fake_run)

    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    kfs = ud.select_keyframes(video, tmp_path, max_frames=3, min_spacing=1.0)
    assert len(kfs) == 3
    ts = [k["t"] for k in kfs]
    assert ts == sorted(ts)
    for k in kfs:
        assert (tmp_path / "keyframes" / k["file"]).exists()
    assert 0.0 in ts


def test_select_keyframes_empty_raises(monkeypatch, tmp_path):
    """_signatures 返回空列表 → RuntimeError。"""
    import pytest

    import skillbrew.understand as ud

    monkeypatch.setattr(ud, "_signatures", lambda _v, _i: [])
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    with pytest.raises(RuntimeError, match="抽帧为空"):
        ud.select_keyframes(video, tmp_path)


def test_select_keyframes_cleans_old_kfs(monkeypatch, tmp_path):
    """重跑时先清空旧 kf_*.jpg。"""
    import subprocess

    import numpy as np

    import skillbrew.understand as ud

    kf_dir = tmp_path / "keyframes"
    kf_dir.mkdir(parents=True, exist_ok=True)
    (kf_dir / "kf_99s.jpg").write_bytes(b"old")

    sigs = [(0.0, np.zeros((_THUMB_H_TEST, _THUMB_W_TEST), dtype=np.float32))]
    monkeypatch.setattr(ud, "_signatures", lambda _v, _i: sigs)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda cmd, **kw: Path(cmd[-1]).write_bytes(b"new"),
    )
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    ud.select_keyframes(video, tmp_path, max_frames=1)
    assert not (kf_dir / "kf_99s.jpg").exists()
