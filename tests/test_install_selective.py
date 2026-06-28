"""install 挑着买（D20）测试：recommend.json 存在时过滤 new 候选；不存在时回退旧行为。"""

from __future__ import annotations

import json
from pathlib import Path

from skillbrew import install as install_mod

V_WORTH = "值得装"
V_NOT_WORTH = "不值得装"


def _build_source(
    tmp_path: Path,
    *,
    items: list[dict],
    decisions: list[dict],
    recommend_judgments: list[dict] | None = None,
) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    raw_base = "https://raw.githubusercontent.com/o/r/main"
    # 补 file.raw_url：和真实 verify 输出一致
    for it in items:
        for f in it.get("files", []):
            f.setdefault("raw_url", f"{raw_base}/{f['path']}")
    install_list = {
        "source_video": "BVtest",
        "verified_repo": {
            "owner": "o",
            "repo": "r",
            "full_name": "o/r",
            "html_url": "https://github.com/o/r",
            "default_branch": "main",
            "stars": 0,
            "stars_observed_at": "t",
            "description": "",
            "how_resolved": "test",
        },
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
    dedup_report = {"decisions": decisions, "summary": {}}
    source.joinpath("dedup.json").write_text(
        json.dumps(dedup_report, ensure_ascii=False), encoding="utf-8"
    )
    if recommend_judgments is not None:
        rec = {
            "judgments": recommend_judgments,
            "summary": {},
            "approved": [j["name"] for j in recommend_judgments if j.get("verdict") == V_WORTH],
        }
        source.joinpath("recommend.json").write_text(
            json.dumps(rec, ensure_ascii=False), encoding="utf-8"
        )
    return source


def _stub_network(monkeypatch, db_path: Path):
    """让 install 真走 approve 分支时不碰网络、不写真实 home。"""
    # 写空 home，避免动到用户真实 ~/.claude
    monkeypatch.setattr(Path, "home", lambda: db_path.parent)
    # stub fetch
    monkeypatch.setattr(install_mod, "_fetch_bytes", lambda url: b"# fake skill\n")
    # stub _install_mcp / _install_repo：测试里不会出现 MCP/repo，无需 stub
    return db_path


def test_install_without_recommend_installs_all_new(tmp_path, monkeypatch):
    """无 recommend.json → 旧行为：所有 dedup=new 的都装（向后兼容）。"""
    items = [
        {
            "name": "a",
            "form": "Skill",
            "dir_path": "skills/a",
            "files": [{"path": "skills/a/SKILL.md", "file_type": "md"}],
            "install_method": "per_file_raw_download",
        },
        {
            "name": "b",
            "form": "Skill",
            "dir_path": "skills/b",
            "files": [{"path": "skills/b/SKILL.md", "file_type": "md"}],
            "install_method": "per_file_raw_download",
        },
    ]
    decisions = [
        {"name": "a", "decision": "new", "category": "productivity", "form": "Skill"},
        {"name": "b", "decision": "new", "category": "productivity", "form": "Skill"},
    ]
    source = _build_source(tmp_path, items=items, decisions=decisions, recommend_judgments=None)
    db_path = tmp_path / "home" / ".claude" / "skillbrew-registry.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "skills"
    _stub_network(monkeypatch, db_path)

    r = install_mod.install(source, target_dir=str(target), approve=True)
    assert set(r["to_install"]) == {"a", "b"}
    assert r["recommend_present"] is False
    assert r["skipped_not_approved"] == []


def test_install_with_recommend_filters_to_approved(tmp_path, monkeypatch):
    """有 recommend.json → 仅装 verdict==V_WORTH 的 new，其它进 skipped_not_approved。"""
    items = [
        {
            "name": "good",
            "form": "Skill",
            "dir_path": "skills/good",
            "files": [{"path": "skills/good/SKILL.md", "file_type": "md"}],
            "install_method": "per_file_raw_download",
        },
        {
            "name": "bad",
            "form": "Skill",
            "dir_path": "skills/bad",
            "files": [{"path": "skills/bad/SKILL.md", "file_type": "md"}],
            "install_method": "per_file_raw_download",
        },
        {
            "name": "meh",
            "form": "Skill",
            "dir_path": "skills/meh",
            "files": [{"path": "skills/meh/SKILL.md", "file_type": "md"}],
            "install_method": "per_file_raw_download",
        },
    ]
    decisions = [
        {"name": "good", "decision": "new", "category": "productivity", "form": "Skill"},
        {"name": "bad", "decision": "new", "category": "productivity", "form": "Skill"},
        {"name": "meh", "decision": "new", "category": "productivity", "form": "Skill"},
        {"name": "merged_old", "decision": "merge", "target": "old"},
        {"name": "already", "decision": "skip"},
    ]
    judgments = [
        {
            "name": "good",
            "decision": "new",
            "verdict": V_WORTH,
            "reason": "ok",
            "score": 8,
            "signals": {},
            "target": None,
            "mode": "ai",
            "form": "Skill",
            "usability": "ready",
        },
        {
            "name": "bad",
            "decision": "new",
            "verdict": V_NOT_WORTH,
            "reason": "junk",
            "score": 2,
            "signals": {},
            "target": None,
            "mode": "ai",
            "form": "Skill",
            "usability": "ready",
        },
        {
            "name": "meh",
            "decision": "new",
            "verdict": V_NOT_WORTH,
            "reason": "dupe-ish",
            "score": 4,
            "signals": {},
            "target": None,
            "mode": "ai",
            "form": "Skill",
            "usability": "ready",
        },
    ]
    source = _build_source(
        tmp_path, items=items, decisions=decisions, recommend_judgments=judgments
    )
    db_path = tmp_path / "home" / ".claude" / "skillbrew-registry.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "skills"
    _stub_network(monkeypatch, db_path)

    r = install_mod.install(source, target_dir=str(target), approve=True)
    assert r["recommend_present"] is True
    assert set(r["to_install"]) == {"good"}
    assert set(r["skipped_not_approved"]) == {"bad", "meh"}
    # merge/skip 仍走老逻辑，不被 recommend 过滤
    assert set(r["skipped_merge"]) == {"merged_old"}
    assert set(r["skipped_already"]) == {"already"}


def test_install_dry_run_recommend_stats(tmp_path, monkeypatch):
    """dry-run 也应该能看到 recommend 过滤后的结果（不碰网络/不碰 home）。"""
    items = [
        {
            "name": "x",
            "form": "Skill",
            "dir_path": "skills/x",
            "files": [{"path": "skills/x/SKILL.md", "file_type": "md"}],
            "install_method": "per_file_raw_download",
        },
    ]
    decisions = [
        {"name": "x", "decision": "new", "category": "productivity", "form": "Skill"},
        {"name": "y", "decision": "new", "category": "productivity", "form": "Skill"},
    ]
    judgments = [
        {
            "name": "x",
            "decision": "new",
            "verdict": V_WORTH,
            "reason": "ok",
            "score": 7,
            "signals": {},
            "target": None,
            "mode": "ai",
            "form": "Skill",
            "usability": "ready",
        },
        {
            "name": "y",
            "decision": "new",
            "verdict": V_NOT_WORTH,
            "reason": "no",
            "score": 3,
            "signals": {},
            "target": None,
            "mode": "ai",
            "form": "Skill",
            "usability": "ready",
        },
    ]
    # y 没有 items 条目：边界情况，install 用 by_name.get(name, {}) 容错
    source = _build_source(
        tmp_path, items=items, decisions=decisions, recommend_judgments=judgments
    )
    # dry-run：不 approve，不碰网络
    r = install_mod.install(source, approve=False)
    assert r["recommend_present"] is True
    assert set(r["to_install"]) == {"x"}
    assert set(r["skipped_not_approved"]) == {"y"}
    text = install_mod.format_plan_text(r)
    assert "已按 recommend.approved 过滤" in text
    assert "不值得装" in text


def test_merge_and_skip_bypass_recommend_filter(tmp_path, monkeypatch):
    """merge/skip/deprecated 不进入 to_install，也不进 skipped_not_approved——
    recommend 过滤只作用在 new 候选上。"""
    items = [
        {
            "name": "keep",
            "form": "Skill",
            "dir_path": "skills/keep",
            "files": [{"path": "skills/keep/SKILL.md", "file_type": "md"}],
            "install_method": "per_file_raw_download",
        },
        {
            "name": "old_stuff",
            "form": "Skill",
            "dir_path": "skills/old",
            "files": [{"path": "skills/old/SKILL.md", "file_type": "md"}],
            "install_method": "per_file_raw_download",
        },
    ]
    decisions = [
        {"name": "keep", "decision": "new", "category": "productivity", "form": "Skill"},
        {"name": "old_stuff", "decision": "new", "category": "deprecated", "form": "Skill"},
        {"name": "merged_one", "decision": "merge", "target": "keep"},
        {"name": "skip_one", "decision": "skip"},
    ]
    judgments = [
        {
            "name": "keep",
            "decision": "new",
            "verdict": V_WORTH,
            "reason": "ok",
            "score": 8,
            "signals": {},
            "target": None,
            "mode": "ai",
            "form": "Skill",
            "usability": "ready",
        },
        # deprecated 的 item 即便 verdict 是值得装，也会被 deprecated 优先拦掉
        {
            "name": "old_stuff",
            "decision": "new",
            "verdict": V_WORTH,
            "reason": "kept",
            "score": 6,
            "signals": {},
            "target": None,
            "mode": "ai",
            "form": "Skill",
            "usability": "ready",
        },
    ]
    source = _build_source(
        tmp_path, items=items, decisions=decisions, recommend_judgments=judgments
    )
    db_path = tmp_path / "home" / ".claude" / "skillbrew-registry.sqlite3"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "skills"
    _stub_network(monkeypatch, db_path)

    r = install_mod.install(source, target_dir=str(target), approve=True)
    assert set(r["to_install"]) == {"keep"}
    assert set(r["skipped_deprecated"]) == {"old_stuff"}
    assert r["skipped_not_approved"] == []
    assert set(r["skipped_merge"]) == {"merged_one"}
    assert set(r["skipped_already"]) == {"skip_one"}
