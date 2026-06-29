"""CLI 进度反馈（_spinner / _print_progress / on_progress 回调）测试。"""

from __future__ import annotations

import io
import sys


def test_spinner_tty_outputs_ok(monkeypatch):
    """TTY 下：进入打 '<msg> ... '，退出打 OK 并换行。"""
    from skillbrew.cli.utils import _spinner

    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    buf = io.StringIO()
    with _spinner("干活中", stream=buf):
        pass
    out = buf.getvalue()
    assert "干活中 ... " in out
    assert out.rstrip("\n").endswith("OK")


def test_spinner_non_tty_outputs_begin_end(monkeypatch):
    """非 TTY（CI/重定向）：两行模式——开始/完成。"""
    from skillbrew.cli.utils import _spinner

    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    buf = io.StringIO()
    with _spinner("干活中", stream=buf):
        pass
    out = buf.getvalue()
    assert "干活中 ... 开始" in out
    assert "干活中 ... 完成" in out


def test_spinner_on_exception_shows_fail(monkeypatch):
    """块内抛异常时，退出打 FAIL 而非 OK，异常原样冒泡。"""
    import pytest

    from skillbrew.cli.utils import _spinner

    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    buf = io.StringIO()
    with pytest.raises(RuntimeError, match="boom"):
        with _spinner("干活中", stream=buf):
            raise RuntimeError("boom")
    out = buf.getvalue()
    assert "FAIL" in out
    assert "OK" not in out


def test_spinner_non_tty_on_exception_shows_fail(monkeypatch):
    """非 TTY 下异常：完成行变 FAIL。"""
    import pytest

    from skillbrew.cli.utils import _spinner

    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    buf = io.StringIO()
    with pytest.raises(RuntimeError, match="boom"):
        with _spinner("干活中", stream=buf):
            raise RuntimeError("boom")
    out = buf.getvalue()
    assert "干活中 ... FAIL" in out


def test_print_progress_tty_inline_cr(monkeypatch):
    """TTY 下：用 \\r 行内刷新，最后换行。"""
    from skillbrew.cli.utils import _print_progress

    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    buf = io.StringIO()
    _print_progress(1, 3, label="a", stream=buf)
    mid = buf.getvalue()
    assert mid.startswith("\r")
    assert "[1/3]" in mid
    assert "\n" not in mid  # 未到终点不换行

    buf2 = io.StringIO()
    _print_progress(3, 3, label="a", stream=buf2)
    final = buf2.getvalue()
    assert final.count("\n") == 1  # 到终点换行一次


def test_print_progress_non_tty_newlines(monkeypatch):
    """非 TTY：每次一行（日志友好），无 \\r。"""
    from skillbrew.cli.utils import _print_progress

    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    buf = io.StringIO()
    _print_progress(1, 3, label="a", stream=buf)
    _print_progress(2, 3, label="b", stream=buf)
    _print_progress(3, 3, label="c", stream=buf)
    lines = [ln for ln in buf.getvalue().split("\n") if ln]
    assert len(lines) == 3
    assert all(not ln.startswith("\r") for ln in lines)
    assert "[1/3]" in lines[0] and "a" in lines[0]
    assert "[2/3]" in lines[1] and "b" in lines[1]
    assert "[3/3]" in lines[2] and "c" in lines[2]


def test_print_progress_pct_when_total(monkeypatch):
    """total>0 时带百分比。"""
    from skillbrew.cli.utils import _print_progress

    monkeypatch.setattr(sys.stderr, "isatty", lambda: False)
    buf = io.StringIO()
    _print_progress(2, 4, stream=buf)
    assert "(50%)" in buf.getvalue()


def test_describe_keyframes_calls_on_progress(monkeypatch, tmp_path):
    """describe_keyframes 每完成一帧回调 on_progress(result, done, total)，done 递增到 total。"""
    import json
    from pathlib import Path

    import skillbrew.llm as llm_mod
    import skillbrew.understand as ud

    kf_dir = tmp_path / "keyframes"
    kf_dir.mkdir()
    # 造 3 张假"关键帧"
    for i, t in enumerate((0, 10, 20)):
        (kf_dir / f"kf_{t}s.jpg").write_bytes(b"fakejpg")

    calls: list[tuple[int, int]] = []

    def _fake_chat_vision(cfg, prompt, img_path, timeout=900.0):
        return f"desc for {Path(img_path).name}"

    monkeypatch.setattr(llm_mod, "chat_vision", _fake_chat_vision)

    cfg = object()
    res = ud.describe_keyframes(
        cfg, tmp_path, max_workers=2, on_progress=lambda r, d, t: calls.append((d, t))
    )
    assert len(res) == 3
    assert len(calls) == 3
    assert calls[-1] == (3, 3)
    # done 单调递增到 total
    dones = [d for d, _ in calls]
    assert sorted(dones) == [1, 2, 3]
    # 落盘
    out = json.loads((tmp_path / "keyframe_visions.json").read_text(encoding="utf-8"))
    assert len(out) == 3
    assert all(x["ok"] for x in out)


def test_on_progress_exception_does_not_crash(monkeypatch, tmp_path):
    """on_progress 自己抛错不影响主流程（defensive except）。"""

    import skillbrew.llm as llm_mod
    import skillbrew.understand as ud

    kf_dir = tmp_path / "keyframes"
    kf_dir.mkdir()
    for t in (0, 10):
        (kf_dir / f"kf_{t}s.jpg").write_bytes(b"fakejpg")

    def _fake_chat_vision(cfg, prompt, img_path, timeout=900.0):
        return "ok"

    monkeypatch.setattr(llm_mod, "chat_vision", _fake_chat_vision)

    def _bad_progress(r, d, t):
        raise RuntimeError("progress callback boom")

    res = ud.describe_keyframes(object(), tmp_path, max_workers=1, on_progress=_bad_progress)
    assert len(res) == 2
    assert all(x["ok"] for x in res)
