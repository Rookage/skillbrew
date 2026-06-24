"""D23 通用安装器 · 第 4 步接线离线单测：install() 的 resolve-pass 行为锁死。

全离线：approve=False（dry-run），resolve-pass 在 dry-run 门之前跑（install.py 925-964
在 1012-1014 之前），所以能观察 to_install / unresolved / resolve_traces / 凭证回写，
既不真装也不联网。monkeypatch 掉 installer.resolve_install_spec 控制其返回值，
不触发真实四级链。

回归门禁（最关键）：默认 ai_infer=False → resolve-pass 整体跳过 → unresolved 原样
透传、resolve_traces 为空、to_install 不被擅自塞入 —— 零行为改变。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from skillbrew import install as install_mod
from skillbrew import installer


# ---------------------------------------------------------------------------
# 夹具：照 test_install_selective._build_source 搭，但 install_list 带 unresolved
# ---------------------------------------------------------------------------

def _build_source(tmp_path: Path, *, unresolved_entries: list[dict] | None = None) -> Path:
    """造一个最小可装源目录：install_list.json（带 unresolved）+ dedup.json。

    items 留空（本次源没有 catalog 命中 item，全在 unresolved 里）；dedup decisions
    也留空——resolve-pass 成功时独立把条目 append 进 to_install，不靠 dedup decisions。
    """
    raw_base = "https://raw.githubusercontent.com/o/test/main"
    install_list = {
        "source_video": "BVtest",
        "verified_repo": {"owner": "o", "repo": "test", "full_name": "o/test",
                          "html_url": "https://github.com/o/test", "default_branch": "main",
                          "stars": 0, "stars_observed_at": "t", "description": "",
                          "how_resolved": "test"},
        "branch": "main",
        "raw_base": raw_base,
        "install_method": "mcp_register",
        "form": "MCP",
        "items": [],
        "unresolved": unresolved_entries or [],
        "generated_at": "t",
    }
    dedup_report = {"decisions": [], "summary": {}}

    source = tmp_path / "source"
    source.mkdir(parents=True, exist_ok=True)
    source.joinpath("install_list.json").write_text(
        json.dumps(install_list, ensure_ascii=False), encoding="utf-8"
    )
    source.joinpath("dedup.json").write_text(
        json.dumps(dedup_report, ensure_ascii=False), encoding="utf-8"
    )
    return source


def _ghost_entries() -> list[dict]:
    """一条 catalog 未收录的 MCP unresolved 条目（带 repo/url，给 AI 推断当源头）。"""
    return [{
        "name": "ghost-mcp",
        "reason": "未在 catalog",
        "candidate": "o/ghost-mcp",
        "source_ref": "1",
        "repo": "o/ghost-mcp",
        "url": "https://github.com/o/ghost-mcp",
    }]


def _hermetic(monkeypatch, tmp_path):
    """别碰真实 home、别真联网（dry-run 其实用不到，留作防御 + 与既有夹具一致）。"""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(install_mod, "_fetch_bytes", lambda url: b"# fake")


# ---------------------------------------------------------------------------
# ① 回归门禁：默认 ai_infer=False → unresolved 原样透传、resolve_traces 空
# ---------------------------------------------------------------------------

def test_default_off_passthrough_unresolved(tmp_path, monkeypatch):
    """--ai-infer 关：resolve-pass 整体跳过，unresolved 一条不少、trace 空、不进 to_install。"""
    _hermetic(monkeypatch, tmp_path)
    src = _build_source(tmp_path, unresolved_entries=_ghost_entries())
    target = tmp_path / "skills"

    # 即便有人误把 resolve 装上，默认关也绝不该调它
    called = {"n": 0}

    def boom(*a, **kw):
        called["n"] += 1
        raise AssertionError("默认关不该调 resolve_install_spec")

    monkeypatch.setattr(installer, "resolve_install_spec", boom)

    plan = install_mod.install(src, target_dir=str(target), approve=False, ai_infer=False)

    assert called["n"] == 0  # 根本没碰 resolve
    assert [u.get("name") for u in plan["unresolved"]] == ["ghost-mcp"]  # 原样透传
    assert plan["resolve_traces"] == []
    assert "ghost-mcp" not in plan["to_install"]
    assert plan["note"].startswith("dry-run")


# ---------------------------------------------------------------------------
# ② ai_infer=True + resolve 成功 → 进 to_install、移出 unresolved、凭证回写
# ---------------------------------------------------------------------------

def test_ai_infer_success_moves_to_install_and_writes_cred(tmp_path, monkeypatch):
    _hermetic(monkeypatch, tmp_path)
    src = _build_source(tmp_path, unresolved_entries=_ghost_entries())
    target = tmp_path / "skills"
    key = "SKILLBREW_TEST_GHOST_KEY"  # 唯一名，测完清掉，绝不污染 os.environ

    def fake_resolve(name, *, repo=None, url=None, allow_ai=False, skip_trial=False,
                     refresh_cache=False, has_tty=False, chat_fn=None, prompt_fn=None):
        assert name == "ghost-mcp"
        return installer.ResolveResult(
            ok=True,
            spec=installer.InstallSpec(
                name="ghost-mcp", command="npx", args=("-y", "ghost-mcp"),
                invoke_hint="AI 推断的幽灵工具", repo=repo, url=url,
            ),
            provenance="ai",
            filled={key: "secret-val"},
            trace=["L3 AI 推断成功", "L4 试跑通过"],
        )

    monkeypatch.setattr(installer, "resolve_install_spec", fake_resolve)

    assert key not in os.environ
    try:
        plan = install_mod.install(
            src, target_dir=str(target), approve=False,
            ai_infer=True, chat_fn=lambda p: "",
        )
        # 成功 → 进安装计划、移出 unresolved
        assert "ghost-mcp" in plan["to_install"]
        assert [u.get("name") for u in plan["unresolved"]] == []
        # trace 有内容且记了成功
        assert any("ghost-mcp" in t for t in plan["resolve_traces"])
        assert any("成功" in t for t in plan["resolve_traces"])
        # 凭证回写 os.environ（关键：否则下游 _credentials_configured 误判「未配」跳过真装）
        assert os.environ.get(key) == "secret-val"
        # items_detail 里能看到这条 MCP 的明细（反黑箱 D22）
        det = next((e for e in plan["items_detail"] if e["name"] == "ghost-mcp"), None)
        assert det is not None and det["form"] == "MCP"
    finally:
        os.environ.pop(key, None)


# ---------------------------------------------------------------------------
# ③ ai_infer=True + resolve 失败 → 留 unresolved、写 reason/missing、不崩
# ---------------------------------------------------------------------------

def test_ai_infer_failure_keeps_unresolved_with_reason(tmp_path, monkeypatch):
    _hermetic(monkeypatch, tmp_path)
    src = _build_source(tmp_path, unresolved_entries=_ghost_entries())
    target = tmp_path / "skills"

    def fake_resolve(name, **kw):
        return installer.ResolveResult(
            ok=False, reason="试跑失败：包不存在", missing=["GHOST_KEY"],
            trace=["L3 推断出装法", "L4 试跑失败"],
        )

    monkeypatch.setattr(installer, "resolve_install_spec", fake_resolve)

    plan = install_mod.install(
        src, target_dir=str(target), approve=False,
        ai_infer=True, chat_fn=lambda p: "",
    )

    # 失败 → 留 unresolved、不进 to_install
    assert "ghost-mcp" in [u.get("name") for u in plan["unresolved"]]
    assert "ghost-mcp" not in plan["to_install"]
    # reason/missing 写进条目（D22 反盲盒透明）
    u = next(x for x in plan["unresolved"] if x.get("name") == "ghost-mcp")
    assert "试跑失败" in (u.get("reason") or "")
    assert u.get("missing") == ["GHOST_KEY"]
    # trace 记了未通过
    assert any("未通过" in t for t in plan["resolve_traces"])


# ---------------------------------------------------------------------------
# ④ resolve 抛异常 → 不崩、留 unresolved、写异常 trace（铁律：绝不中断安装）
# ---------------------------------------------------------------------------

def test_ai_infer_resolve_exception_does_not_crash(tmp_path, monkeypatch):
    _hermetic(monkeypatch, tmp_path)
    src = _build_source(tmp_path, unresolved_entries=_ghost_entries())
    target = tmp_path / "skills"

    def boom(name, **kw):
        raise RuntimeError("网络抽风")

    monkeypatch.setattr(installer, "resolve_install_spec", boom)

    plan = install_mod.install(
        src, target_dir=str(target), approve=False,
        ai_infer=True, chat_fn=lambda p: "",
    )

    # 异常被吞，不崩；条目仍留 unresolved
    assert "ghost-mcp" in [u.get("name") for u in plan["unresolved"]]
    assert "ghost-mcp" not in plan["to_install"]
    assert any("异常" in t and "ghost-mcp" in t for t in plan["resolve_traces"])
