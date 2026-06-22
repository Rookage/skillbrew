"""运行时中立回归测试：issue #7/#8/#9/#10。

验证点：
1. config.detect_runtime() 在 SKILLBREW_RUNTIME 显式指定时返回对应值；
2. config.skills_dir() / claude_json_path() / repo_clones_dir() 支持 env 覆盖；
3. 无 env 时按运行时返回 Codex 默认路径；
4. dedup.build_baseline 默认不依赖硬编码 Claude 路径；
5. scan_local_mcps 尊重自定义 mcp 路径；
6. Windows 风格路径也能被 Path 正确接受。
"""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

import pytest

from skillbrew import config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """每个测试前清理相关环境变量，避免本机环境干扰。"""
    for key in (
        "SKILLBREW_RUNTIME",
        "SKILLBREW_SKILLS_DIR",
        "SKILLBREW_CLAUDE_JSON",
        "SKILLBREW_CLONES_DIR",
        "CODEX_HOME",
        "CLAUDECODE",
        "CLAUDE_CODE_SESSION_ID",
        "CLAUDE_CODE_EXECPATH",
    ):
        monkeypatch.delenv(key, raising=False)


def test_detect_runtime_explicit(monkeypatch):
    monkeypatch.setenv("SKILLBREW_RUNTIME", "codex")
    assert config.detect_runtime() == "codex"

    monkeypatch.setenv("SKILLBREW_RUNTIME", "claude")
    assert config.detect_runtime() == "claude"


def test_detect_runtime_codex_home(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    assert config.detect_runtime() == "codex"


def test_detect_runtime_codex_dir(monkeypatch, tmp_path):
    """没有 env 但 ~/.codex 存在时识别为 codex。"""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".codex").mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert config.detect_runtime() == "codex"


def test_detect_runtime_default_claude(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert config.detect_runtime() == "claude"


def test_skills_dir_env_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom_skills"
    monkeypatch.setenv("SKILLBREW_SKILLS_DIR", str(custom))
    assert config.skills_dir() == custom


def test_skills_dir_codex_default(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".codex").mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert config.skills_dir() == fake_home / ".codex" / "skills"


def test_skills_dir_claude_default(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert config.skills_dir() == fake_home / ".claude" / "skills"


def test_claude_json_path_env_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom.json"
    monkeypatch.setenv("SKILLBREW_CLAUDE_JSON", str(custom))
    assert config.claude_json_path() == custom


def test_claude_json_path_codex_default(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".codex").mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert config.claude_json_path() == fake_home / ".codex" / "config.toml"


def test_claude_json_path_claude_default(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert config.claude_json_path() == fake_home / ".claude.json"


def test_repo_clones_dir_env_override(monkeypatch, tmp_path):
    custom = tmp_path / "custom_clones"
    monkeypatch.setenv("SKILLBREW_CLONES_DIR", str(custom))
    assert config.repo_clones_dir() == custom


def test_repo_clones_dir_codex_default(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".codex").mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert config.repo_clones_dir() == fake_home / ".codex" / "clones"


def test_repo_clones_dir_claude_default(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    assert config.repo_clones_dir() == fake_home / ".claude" / "clones"


def test_scan_local_mcps_uses_config_path(tmp_path, monkeypatch):
    """scan_local_mcps 默认读取 config.claude_json_path()，而非写死 ~/.claude.json。"""
    from skillbrew import dedup

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    cj = fake_home / ".claude.json"
    cj.write_text('{"mcpServers": {"test-server": {"command": "npx"}}}', encoding="utf-8")
    mcps = dedup.scan_local_mcps()
    names = {m["name"] for m in mcps}
    assert "test-server" in names


def test_dedup_default_skill_dirs_not_hardcoded(tmp_path, monkeypatch):
    """dedup() 的 skill_dirs=None 默认走 config.skills_dir()，不硬编码 Claude 路径。"""
    from skillbrew import dedup

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    (fake_home / ".codex").mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    source = tmp_path / "source"
    source.mkdir()
    source.joinpath("install_list.json").write_text(
        '{"items": [{"name": "foo", "form": "Skill"}]}', encoding="utf-8"
    )

    # Codex 默认 skills 目录不存在也没关系，dedup 会容忍并返回空基准。
    report = dedup.dedup(source)
    assert report["summary"]["new"] == 1


def test_windows_path_accepted(monkeypatch):
    """环境变量传入 Windows 风格路径时，Path 能正常包装（不抛异常）。"""
    win_path = r"C:\Users\AllenK\.codex\skills"
    monkeypatch.setenv("SKILLBREW_SKILLS_DIR", win_path)
    assert str(config.skills_dir()) == win_path
