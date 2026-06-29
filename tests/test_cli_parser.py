"""cli.parser 装配与全局标志透传测试。"""

from __future__ import annotations

import os


def test_build_parser_returns_parser():
    """build_parser 返回 argparse.ArgumentParser，prog=skillbrew。"""
    import argparse

    from skillbrew.cli.parser import build_parser

    p = build_parser()
    assert isinstance(p, argparse.ArgumentParser)
    assert p.prog == "skillbrew"


def test_parse_args_run_defaults():
    """run 子命令默认值：qn=32, max_frames=5, max_workers=3, skip_asr/vision/force=False。"""
    from skillbrew.cli.parser import parse_args

    args = parse_args(["run", "https://www.bilibili.com/video/BV1xx"])
    assert args.cmd == "run"
    assert args.source.startswith("https://")
    assert args.qn == 32
    assert args.max_frames == 5
    assert args.max_workers == 3
    assert args.skip_asr is False
    assert args.skip_vision is False
    assert args.force is False
    assert callable(args.func)


def test_parse_args_install_flags():
    """install 子命令默认 dry-run；--approve/--ai-infer/--no-trial/--refresh-cache 能打。"""
    from skillbrew.cli.parser import parse_args

    a = parse_args(["install", "/tmp/src"])
    assert a.approve is False
    assert a.ai_infer is False
    assert a.no_trial is False
    assert a.refresh_cache is False
    assert a.include_deprecated is False
    assert a.target_dir is None

    a = parse_args(
        [
            "install",
            "/tmp/src",
            "--approve",
            "--ai-infer",
            "--no-trial",
            "--refresh-cache",
            "--include-deprecated",
            "--target-dir",
            "/tmp/skills",
        ]
    )
    assert a.approve is True
    assert a.ai_infer is True
    assert a.no_trial is True
    assert a.refresh_cache is True
    assert a.include_deprecated is True
    assert a.target_dir == "/tmp/skills"


def test_parse_args_global_flags_propagate_env(monkeypatch):
    """--runtime/--clones-dir/--mcp-json 透传为环境变量（setdefault 不覆盖已有）。"""
    from skillbrew.cli.parser import parse_args

    # 清掉可能残留的 env
    for k in (
        "SKILLBREW_RUNTIME",
        "SKILLBREW_CLONES_DIR",
        "SKILLBREW_CLAUDE_JSON",
    ):
        monkeypatch.delenv(k, raising=False)

    parse_args(
        [
            "--runtime",
            "codex",
            "--clones-dir",
            "/tmp/clones",
            "--mcp-json",
            "/tmp/cfg.json",
            "doctor",
        ]
    )
    assert os.environ.get("SKILLBREW_RUNTIME") == "codex"
    assert os.environ.get("SKILLBREW_CLONES_DIR") == "/tmp/clones"
    assert os.environ.get("SKILLBREW_CLAUDE_JSON") == "/tmp/cfg.json"


def test_parse_args_global_flags_do_not_override_existing_env(monkeypatch):
    """setdefault 语义：已有 env 时 CLI 全局标志不覆盖。"""
    from skillbrew.cli.parser import parse_args

    monkeypatch.setenv("SKILLBREW_RUNTIME", "claude")
    parse_args(["--runtime", "codex", "doctor"])
    assert os.environ["SKILLBREW_RUNTIME"] == "claude"  # 保留原值


def test_parse_args_recommend_mode_choices():
    """recommend --mode 只接受 keyword/manual/ai。"""
    import pytest

    from skillbrew.cli.parser import parse_args

    for m in ("keyword", "manual", "ai"):
        a = parse_args(["recommend", "/tmp/src", "--mode", m])
        assert a.mode == m

    with pytest.raises(SystemExit):
        parse_args(["recommend", "/tmp/src", "--mode", "bogus"])


def test_parse_args_dedup_multiple_skills_dir():
    """dedup --skills-dir 可重复，append 到 list。"""
    from skillbrew.cli.parser import parse_args

    a = parse_args(
        ["dedup", "/tmp/src", "--skills-dir", "/a", "--skills-dir", "/b"]
    )
    assert a.skills_dir == ["/a", "/b"]


def test_parse_args_version_exits(monkeypatch):
    """--version 打印版本并 exit。"""
    import pytest

    from skillbrew.cli.parser import parse_args

    with pytest.raises(SystemExit) as ei:
        parse_args(["--version"])
    assert ei.value.code == 0


def test_parse_args_no_subcommand_exits():
    """无子命令时 argparse 因 required=True 报错退出。"""
    import pytest

    from skillbrew.cli.parser import parse_args

    with pytest.raises(SystemExit):
        parse_args([])


def test_all_subparsers_have_func():
    """11 个子命令都 set_defaults(func=...)。"""
    from skillbrew.cli.parser import build_parser

    p = build_parser()
    subs = [
        "doctor",
        "config",
        "run",
        "ingest",
        "understand",
        "plan",
        "verify",
        "dedup",
        "recommend",
        "install",
        "record",
    ]
    # 没有直接 API 读 subparsers，绕一下：每个子命令都能被 parse 且 func 可调用
    for name in subs:
        # install 之后都需要 source 参数
        if name in ("doctor", "config"):
            argv = [name]
        else:
            argv = [name, "/tmp/fake"]
        args = p.parse_args(argv)
        assert callable(args.func), f"{name} 没挂 func"


def test_verify_repo_override():
    """verify 支持 --repo owner/name 手动指定仓库。"""
    from skillbrew.cli.parser import parse_args

    a = parse_args(["verify", "/tmp/src", "--repo", "foo/bar"])
    assert a.repo == "foo/bar"
    a2 = parse_args(["verify", "/tmp/src"])
    assert a2.repo is None


def test_understand_skip_flags():
    """understand --skip-asr --skip-vision 能打。"""
    from skillbrew.cli.parser import parse_args

    a = parse_args(["understand", "/tmp/src", "--skip-asr", "--skip-vision"])
    assert a.skip_asr is True
    assert a.skip_vision is True


def test_doctor_vision_flag():
    """doctor --vision 可选。"""
    from skillbrew.cli.parser import parse_args

    a = parse_args(["doctor", "--vision"])
    assert a.vision is True
    a2 = parse_args(["doctor"])
    assert a2.vision is False
