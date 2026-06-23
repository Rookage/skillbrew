"""R1 调度器 MVP：已装能力索引 INSTALLED_INDEX.md + CLAUDE.md sentinel 注入测试。"""
from __future__ import annotations

import json
import os
from pathlib import Path

from skillbrew import record as record_mod
from skillbrew import config, registry


def _make_source(tmp_path: Path, items: list[dict], decisions: list[dict]) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    raw_base = "https://raw.githubusercontent.com/o/r/main"
    for it in items:
        for f in it.get("files", []):
            f.setdefault("raw_url", f"{raw_base}/{f['path']}")
    install_list = {
        "source_video": "BVtest",
        "verified_repo": {"owner": "o", "repo": "r", "full_name": "o/r",
                          "html_url": "https://github.com/o/r", "default_branch": "main",
                          "stars": 0, "stars_observed_at": "t", "description": "",
                          "how_resolved": "test"},
        "branch": "main",
        "raw_base": raw_base,
        "install_method": "per_file_raw_download",
        "form": "Skill",
        "items": items,
        "generated_at": "t",
    }
    source.joinpath("install_list.json").write_text(
        json.dumps(install_list, ensure_ascii=False), encoding="utf-8"
    )
    dd = {
        "decisions": decisions,
        "summary": {},
        "baseline": {"skill_dirs": []},
    }
    source.joinpath("dedup.json").write_text(
        json.dumps(dd, ensure_ascii=False), encoding="utf-8"
    )
    return source


def _stub_home(monkeypatch, home: Path):
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("SKILLBREW_CLAUDE_HOME", str(home / ".claude"))


def _preseed_skill(skills_dir: Path, name: str, desc: str) -> Path:
    """在 skills_dir 放一个 SKILL.md（带 frontmatter description），返回 install_path。"""
    p = skills_dir / name
    p.mkdir(parents=True, exist_ok=True)
    sk = (
        "---\n"
        f"name: {name}\n"
        f'description: "{desc}"\n'
        "---\n"
        f"# {name}\n"
        f"{desc} 的正文...\n"
    )
    (p / "SKILL.md").write_text(sk, encoding="utf-8")
    return p


def _preseed_registry(db_path: Path, skills: list[dict]) -> None:
    conn = registry.connect(db_path)
    try:
        for s in skills:
            conn.execute(
                "INSERT INTO skills (name,display_name,category,form,source,install_path,"
                "file_count,status,notes,installed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (s["name"], s.get("display_name") or s["name"], s.get("category", "misc"),
                 s.get("form", "Skill"), s.get("source", "test"),
                 s.get("install_path") or "", s.get("file_count", 1),
                 s.get("status", "active"), s.get("notes", ""),
                 s.get("installed_at", "2026-06-23T00:00:00")),
            )
        conn.commit()
    finally:
        conn.close()


def test_record_writes_installed_index_and_claude_md(tmp_path, monkeypatch):
    """record() 完成 RECORD/DASHBOARD 后，应写 INSTALLED_INDEX.md 并注入 CLAUDE.md sentinel。"""
    home = tmp_path / "home"
    _stub_home(monkeypatch, home)
    skills_dir = home / ".claude" / "skills"
    ip_a = _preseed_skill(skills_dir, "alpha", "做 A 事情的技能")
    ip_b = _preseed_skill(skills_dir, "beta", "做 B 事情的技能")
    db_path = home / ".claude" / "skillbrew-registry.sqlite3"
    _preseed_registry(db_path, [
        {"name": "alpha", "install_path": str(ip_a)},
        {"name": "beta", "install_path": str(ip_b), "form": "MCP",
         "source": "gh-mcp", "notes": "测试 MCP 条目"},
    ])

    source = _make_source(tmp_path, items=[], decisions=[])
    r = record_mod.record(source, db_path=db_path)

    index_path = home / ".claude" / "INSTALLED_INDEX.md"
    claude_md = home / ".claude" / "CLAUDE.md"
    assert index_path.exists(), "INSTALLED_INDEX.md 应被写出"
    assert claude_md.exists(), "CLAUDE.md 应被写出/初始化"

    idx = index_path.read_text(encoding="utf-8")
    assert "已装能力索引" in idx
    assert "alpha" in idx
    assert "beta" in idx
    # Skill 段 / MCP 段都在
    assert "Skill（技能）" in idx
    assert "MCP 服务器" in idx
    # alpha description 是从 SKILL.md frontmatter 抠的
    assert "做 A 事情的技能" in idx
    # MCP 有 notes，用 notes 当描述
    assert "测试 MCP 条目" in idx

    md = claude_md.read_text(encoding="utf-8")
    assert record_mod._INDEX_BEGIN in md
    assert record_mod._INDEX_END in md
    assert "INSTALLED_INDEX.md" in md
    assert r.get("installed_index")
    assert r["installed_index"]["active_count"] == 2


def test_record_idempotent_no_duplicate_sentinel(tmp_path, monkeypatch):
    """重复调用 record()，CLAUDE.md 里 sentinel 块应只出现一次（幂等）。"""
    home = tmp_path / "home"
    _stub_home(monkeypatch, home)
    db_path = home / ".claude" / "skillbrew-registry.sqlite3"
    _preseed_registry(db_path, [{"name": "only", "install_path": "/tmp/only"}])
    source = _make_source(tmp_path, items=[], decisions=[])
    record_mod.record(source, db_path=db_path)
    record_mod.record(source, db_path=db_path)
    md = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
    assert md.count(record_mod._INDEX_BEGIN) == 1
    assert md.count(record_mod._INDEX_END) == 1


def test_record_appends_sentinel_to_existing_claude_md(tmp_path, monkeypatch):
    """CLAUDE.md 已有用户内容时，sentinel 应追加到末尾而不覆盖原文。"""
    home = tmp_path / "home"
    _stub_home(monkeypatch, home)
    claude_md = home / ".claude" / "CLAUDE.md"
    claude_md.parent.mkdir(parents=True, exist_ok=True)
    user_text = "# My Project\n\n这里是用户自己写的规则，不能被覆盖。\n"
    claude_md.write_text(user_text, encoding="utf-8")
    db_path = home / ".claude" / "skillbrew-registry.sqlite3"
    _preseed_registry(db_path, [{"name": "x", "install_path": "/x"}])
    source = _make_source(tmp_path, items=[], decisions=[])
    record_mod.record(source, db_path=db_path)
    md = claude_md.read_text(encoding="utf-8")
    assert "这里是用户自己写的规则" in md
    assert md.count(record_mod._INDEX_BEGIN) == 1
    # 用户原文应在 sentinel 之前
    assert md.find("这里是用户自己写的规则") < md.find(record_mod._INDEX_BEGIN)


def test_record_skips_index_when_env_opt_out(tmp_path, monkeypatch):
    """设 SKILLBREW_NO_INDEX=1 时不写 INSTALLED_INDEX.md / 不改 CLAUDE.md。"""
    home = tmp_path / "home"
    _stub_home(monkeypatch, home)
    monkeypatch.setenv("SKILLBREW_NO_INDEX", "1")
    db_path = home / ".claude" / "skillbrew-registry.sqlite3"
    _preseed_registry(db_path, [{"name": "x", "install_path": "/x"}])
    source = _make_source(tmp_path, items=[], decisions=[])
    r = record_mod.record(source, db_path=db_path)
    assert not (home / ".claude" / "INSTALLED_INDEX.md").exists()
    assert not (home / ".claude" / "CLAUDE.md").exists()
    assert "installed_index" not in r


def test_record_index_failure_does_not_crash(tmp_path, monkeypatch):
    """写索引出错时（如 claude_home 路径不可写）不应让 record() 主流程崩。"""
    home = tmp_path / "home"
    _stub_home(monkeypatch, home)
    db_path = home / ".claude" / "skillbrew-registry.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _preseed_registry(db_path, [{"name": "x", "install_path": "/x"}])
    source = _make_source(tmp_path, items=[], decisions=[])
    # 用 monkeypatch 让 config.claude_home() 返回一个其父是普通文件的路径，
    # 这样 home.mkdir(parents=True) 必然 NotADirectoryError，触发 except 分支
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file, not a dir", encoding="utf-8")
    monkeypatch.setattr(record_mod.config, "claude_home",
                        lambda: blocker / ".claude")
    # 不应抛
    r = record_mod.record(source, db_path=db_path)
    assert r["record_path"]  # RECORD.md 仍应写出
    assert "installed_index" not in r  # 但索引失败不出现在结果里
