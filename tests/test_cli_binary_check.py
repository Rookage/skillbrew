"""CLI 外部二进制依赖预检测试。"""

from __future__ import annotations

import shutil


def test_require_binaries_missing():
    """一定不存在的工具会被检出。"""
    from skillbrew.cli.utils import _require_binaries

    missing = _require_binaries("definitely_not_a_real_binary_xyz123")
    assert "definitely_not_a_real_binary_xyz123" in missing


def test_require_binaries_mixed(monkeypatch):
    """混合存在/缺失：只返回缺失的。"""
    from skillbrew.cli.utils import _require_binaries

    fake_which = {"exists_tool": "/usr/bin/exists_tool"}.get
    monkeypatch.setattr(shutil, "which", fake_which)
    missing = _require_binaries("exists_tool", "missing_tool")
    assert missing == ["missing_tool"]


def test_format_missing_hint_contains_tool_name():
    """提示信息里包含工具名。"""
    from skillbrew.cli.utils import _format_missing_hint

    msg = _format_missing_hint(["ffmpeg"])
    assert "ffmpeg" in msg
    assert "缺依赖" in msg
    assert "装好后重跑" in msg


def test_format_missing_hint_linux_install_command(monkeypatch):
    """Linux 下给出 apt 安装命令。"""
    import platform

    from skillbrew.cli.utils import _format_missing_hint

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    msg = _format_missing_hint(["ffmpeg"])
    assert "apt install ffmpeg" in msg


def test_format_missing_hint_unknown_binary_no_crash():
    """未知工具（hints 里没配）不应崩溃，至少列出工具名。"""
    from skillbrew.cli.utils import _format_missing_hint

    msg = _format_missing_hint(["some_weird_tool_99"])
    assert "some_weird_tool_99" in msg


# ---- cmd_ingest/cmd_understand 预检拦截 ----
# 不真正走下载/网络；monkeypatch load_config 返回极简对象，
# 并把下游 fetch_xxx / transcribe 打成爆炸桩——如果预检没拦住就会真调进去炸。


def test_ingest_webpage_does_not_require_ffmpeg(monkeypatch, capsys, tmp_path):
    """网页/文本源不需要 ffmpeg，即使 ffmpeg 缺失也能越过预检。"""
    from skillbrew.cli.commands import ingest as ingest_cmd
    from skillbrew.config import Config, ProviderConfig

    monkeypatch.setattr(shutil, "which", lambda _: None)

    empty = ProviderConfig(base_url="", api_key="", model="")
    dummy_cfg = Config(text=empty, vision=empty, env_path=tmp_path / ".env")
    from skillbrew import config as _cfg_mod

    monkeypatch.setattr(_cfg_mod, "project_root", lambda: tmp_path)
    monkeypatch.setattr(_cfg_mod, "load_config", lambda: dummy_cfg)

    # fetch_webpage 做桩：走到这里即代表预检过了
    reached = {"ok": False}

    class _Dummy:
        title = "x"
        text = "hello"
        text_path = tmp_path / "t.txt"

    def _fake_fetch_webpage(url, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        reached["ok"] = True
        return _Dummy()

    monkeypatch.setattr("skillbrew.ingest.fetch_webpage", _fake_fetch_webpage)

    args = type("A", (), {"source": "https://example.com/page", "qn": 32})()
    rc = ingest_cmd.cmd_ingest(args)
    assert reached["ok"], "网页源应该越过二进制预检进入 fetch_webpage"
    assert rc == 0
    out = capsys.readouterr()
    assert "缺依赖" not in (out.out + out.err)


def test_ingest_bilibili_requires_ffmpeg(monkeypatch, capsys, tmp_path):
    """B站视频源在缺 ffmpeg 时必须在预检阶段就 return 1。"""
    from skillbrew.cli.commands import ingest as ingest_cmd
    from skillbrew.config import Config, ProviderConfig

    monkeypatch.setattr(shutil, "which", lambda _: None)

    empty = ProviderConfig(base_url="", api_key="", model="")
    dummy_cfg = Config(text=empty, vision=empty, env_path=tmp_path / ".env")
    from skillbrew import config as _cfg_mod

    monkeypatch.setattr(_cfg_mod, "project_root", lambda: tmp_path)
    monkeypatch.setattr(_cfg_mod, "load_config", lambda: dummy_cfg)

    # 如果代码没在预检处拦住，真走到 fetch_bilibili 会网络请求/报错；
    # 用桩标记是否被调用来确认"未到达"。
    reached = {"fetch_bilibili": False}

    def _boom(*a, **kw):
        reached["fetch_bilibili"] = True
        raise AssertionError("预检应拦住，不该走到 fetch_bilibili")

    monkeypatch.setattr("skillbrew.ingest.fetch_bilibili", _boom)

    args = type("A", (), {"source": "BV1xx411c7mD", "qn": 32})()
    rc = ingest_cmd.cmd_ingest(args)
    assert rc == 1
    assert not reached["fetch_bilibili"]
    err = capsys.readouterr().err
    assert "ffmpeg" in err
    assert "缺依赖" in err


def test_ingest_douyin_requires_both(monkeypatch, capsys, tmp_path):
    """抖音需要 ffmpeg+yt-dlp；只有 ffmpeg 时仍要在预检阶段拦截提示缺 yt-dlp。"""
    from skillbrew.cli.commands import ingest as ingest_cmd
    from skillbrew.config import Config, ProviderConfig

    def _which(name):
        return "/usr/bin/ffmpeg" if name == "ffmpeg" else None

    monkeypatch.setattr(shutil, "which", _which)

    empty = ProviderConfig(base_url="", api_key="", model="")
    dummy_cfg = Config(text=empty, vision=empty, env_path=tmp_path / ".env")
    from skillbrew import config as _cfg_mod

    monkeypatch.setattr(_cfg_mod, "project_root", lambda: tmp_path)
    monkeypatch.setattr(_cfg_mod, "load_config", lambda: dummy_cfg)

    reached = {"fetch": False}

    def _boom(*a, **kw):
        reached["fetch"] = True
        raise AssertionError("不该走到 fetch_douyin")

    monkeypatch.setattr("skillbrew.ingest.fetch_douyin", _boom)

    args = type("A", (), {"source": "1234567890", "qn": 32})()
    rc = ingest_cmd.cmd_ingest(args)
    assert rc == 1
    assert not reached["fetch"]
    err = capsys.readouterr().err
    assert "yt-dlp" in err


def test_understand_requires_ffmpeg(monkeypatch, capsys, tmp_path):
    """understand 在 video.mp4 存在但缺 ffmpeg 时必须 return 1。"""
    from skillbrew.cli.commands import understand as understand_cmd
    from skillbrew.config import Config, ProviderConfig

    monkeypatch.setattr(shutil, "which", lambda _: None)

    src_dir = tmp_path / "sources" / "BV1xx"
    src_dir.mkdir(parents=True)
    (src_dir / "video.mp4").write_bytes(b"fake")

    empty = ProviderConfig(base_url="", api_key="", model="")
    dummy_cfg = Config(text=empty, vision=empty, env_path=tmp_path / ".env")
    from skillbrew import config as _cfg_mod

    monkeypatch.setattr(_cfg_mod, "project_root", lambda: tmp_path)
    monkeypatch.setattr(_cfg_mod, "load_config", lambda: dummy_cfg)

    # 走到 transcribe 即代表预检漏了
    reached = {"transcribe": False}

    def _boom(*a, **kw):
        reached["transcribe"] = True
        raise AssertionError("不该走到 transcribe")

    monkeypatch.setattr("skillbrew.understand.transcribe", _boom)

    args = type(
        "A",
        (),
        {
            "source": str(src_dir),
            "skip_asr": False,
            "skip_vision": True,
            "force": False,
            "max_frames": 5,
            "max_workers": 2,
        },
    )()
    rc = understand_cmd.cmd_understand(args)
    assert rc == 1
    assert not reached["transcribe"]
    err = capsys.readouterr().err
    assert "ffmpeg" in err
