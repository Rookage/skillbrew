"""D23 通用安装器 · 第 3 步离线单测：infer / verify / prompt / resolve 全链。

全离线：monkeypatch 掉 chat_fn / subprocess / verify 的网络抓取助手，不真联网、
不真调 LLM（大语言模型）、不真起子进程。覆盖每级降级成功与失败路径，确保
「不崩、不静默、不臆造」（D23 铁律）。
"""
from __future__ import annotations

import subprocess

from skillbrew import config, installer, verify
from skillbrew.installer import InstallSpec


# ---- 通用造数据 ----

def _spec(**kw) -> InstallSpec:
    """造一个最小可用 InstallSpec，默认填好必填字段，kw 覆盖。"""
    base = dict(name="x", command="npx", args=("-y", "x"), invoke_hint="提示")
    base.update(kw)
    return InstallSpec(**base)


def _patch_github(monkeypatch, *, exists=True, files=None):
    """monkeypatch 掉 verify 的网络抓取三件套：probe_repo / list_tree / _raw_text。
    raw_url 不用 patch（纯字符串拼接）。"""
    monkeypatch.setattr(
        verify,
        "probe_repo",
        lambda o, r: {
            "owner": o,
            "repo": r,
            "full_name": f"{o}/{r}",
            "html_url": f"https://github.com/{o}/{r}",
            "stars": 1,
            "default_branch": "main",
            "description": "a mcp",
            "pushed_at": None,
        }
        if exists
        else None,
    )
    tree = [{"path": f, "type": "blob", "size": 10} for f in (files or [])]
    monkeypatch.setattr(verify, "list_tree", lambda o, r, b: tree)
    monkeypatch.setattr(verify, "_raw_text", lambda u: "# readme\nuse npx -y foo-mcp")


def _cache_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "install_cache_path", lambda: tmp_path / "install_cache.json")


def _ok_run(monkeypatch):
    """subprocess.run 永远返回退出码 0（包已解析）。"""
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, b"", b"")
    )


# ---------------------------------------------------------------------------
# verify_install_spec
# ---------------------------------------------------------------------------

def test_verify_skip_returns_ok():
    r = installer.verify_install_spec(_spec(), skip=True)
    assert r.ok is True
    assert any("skipped" in a for a in r.attempts)


def test_verify_exit_zero_ok(monkeypatch):
    _ok_run(monkeypatch)
    r = installer.verify_install_spec(_spec(command="npx", args=("-y", "pkg")))
    assert r.ok is True


def test_verify_file_not_found_fails(monkeypatch):
    def fake_run(cmd, **kw):
        raise FileNotFoundError("no npx")
    monkeypatch.setattr(subprocess, "run", fake_run)
    r = installer.verify_install_spec(_spec(command="npx"))
    assert r.ok is False
    assert "不可用" in r.reason


def test_verify_timeout_is_ok_stdio(monkeypatch):
    def fake_run(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 20)
    monkeypatch.setattr(subprocess, "run", fake_run)
    r = installer.verify_install_spec(_spec(command="npx", args=("-y", "pkg")))
    assert r.ok is True  # stdio 服务器超时属正常
    assert any("超时" in t for t in r.trace)


def test_verify_not_found_signal_retries_then_fails(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"npm ERR 404 not found")
    monkeypatch.setattr(subprocess, "run", fake_run)
    r = installer.verify_install_spec(_spec(command="npx", args=("-y", "ghost")))
    assert r.ok is False
    assert len(r.attempts) == 2  # --help 与 --version 都试过


def test_verify_nonzero_without_notfound_signal_ok(monkeypatch):
    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 2, stdout=b"", stderr=b"unknown option --help")
    monkeypatch.setattr(subprocess, "run", fake_run)
    r = installer.verify_install_spec(_spec(command="npx", args=("-y", "pkg")))
    assert r.ok is True  # 包解析了，只是不认 --help


def test_verify_placeholder_arg_replaced(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    installer.verify_install_spec(
        _spec(command="uvx", args=("mcp-server-sqlite", "--db-path", "<DB_PATH>"))
    )
    # <DB_PATH> 被替换成 x，不原样传
    assert "<DB_PATH>" not in seen["cmd"]
    assert "x" in seen["cmd"]


# ---------------------------------------------------------------------------
# prompt_missing
# ---------------------------------------------------------------------------

def test_prompt_empty_missing():
    r = installer.prompt_missing(_spec(missing=[]), has_tty=True)
    assert r.filled == {}
    assert r.skipped == []


def test_prompt_headless_skips_all():
    r = installer.prompt_missing(_spec(missing=["A", "B"]), has_tty=False)
    assert r.filled == {}
    assert r.skipped == ["A", "B"]
    assert r.via == "report"


def test_prompt_tty_with_prompt_fn():
    def pf(var):
        return "val" if var == "A" else ""
    r = installer.prompt_missing(_spec(missing=["A", "B"]), has_tty=True, prompt_fn=pf)
    assert r.filled == {"A": "val"}
    assert r.skipped == ["B"]
    assert r.via == "tty"


def test_prompt_fn_works_headless_too():
    """headless 但注入 prompt_fn（如 agent 在对话里转达）也能填。"""
    def pf(var):
        return "k"
    r = installer.prompt_missing(_spec(missing=["A"]), has_tty=False, prompt_fn=pf)
    assert r.filled == {"A": "k"}
    assert r.via == "tty"


# ---------------------------------------------------------------------------
# infer_install_spec
# ---------------------------------------------------------------------------

def test_infer_success(monkeypatch):
    _patch_github(monkeypatch, files=["README.md", "package.json"])
    chat = lambda p: (  # noqa: E731
        '{"name":"foo-mcp","command":"npx","args":["-y","foo-mcp"],'
        '"invoke_hint":"foo","credential_env":["FOO_KEY"]}'
    )
    res = installer.infer_install_spec("o/foo", chat)
    assert res.ok is True
    assert res.spec is not None
    assert res.spec.provenance == "ai_unverified"
    assert res.spec.verify_ok is False
    assert res.spec.command == "npx"
    assert res.spec.args == ("-y", "foo-mcp")
    assert res.spec.credential_env == ("FOO_KEY",)
    # FOO_KEY 不在 env → missing
    assert "FOO_KEY" in res.spec.missing
    # D14：env_template 值强制空
    assert res.spec.env_template == {"FOO_KEY": ""}


def test_infer_bad_repo_returns_fail():
    res = installer.infer_install_spec("不是仓库地址", lambda p: "")
    assert res.ok is False
    assert "无法解析" in res.reason


def test_infer_repo_not_found(monkeypatch):
    _patch_github(monkeypatch, exists=False)
    res = installer.infer_install_spec("o/ghost", lambda p: "")
    assert res.ok is False
    assert "不存在" in res.reason


def test_infer_chat_fn_raises(monkeypatch):
    _patch_github(monkeypatch, files=["README.md"])

    def boom(p):
        raise RuntimeError("quota")

    res = installer.infer_install_spec("o/foo", boom)
    assert res.ok is False
    assert "AI 调用失败" in res.reason


def test_infer_bad_json(monkeypatch):
    _patch_github(monkeypatch, files=["README.md"])
    res = installer.infer_install_spec("o/foo", lambda p: "这不是 json")
    assert res.ok is False
    assert "JSON" in res.reason


def test_infer_missing_fields(monkeypatch):
    _patch_github(monkeypatch, files=["README.md"])
    res = installer.infer_install_spec("o/foo", lambda p: '{"name":"x"}')
    assert res.ok is False
    assert "字段" in res.reason


def test_infer_forces_env_values_empty_d14(monkeypatch):
    """D14：AI 即便在 env_template 里塞了真 key，也强制抹成空串，绝不留在 spec 上。"""
    _patch_github(monkeypatch, files=["README.md"])
    chat = lambda p: (  # noqa: E731
        '{"name":"foo","command":"npx","args":["foo"],'
        '"env_template":{"K":"sk-leaky-1234567890"},"credential_env":["K"]}'
    )
    res = installer.infer_install_spec("o/foo", chat)
    assert res.ok is True
    assert res.spec.env_template == {"K": ""}  # 值被抹掉，绝不留 key


# ---------------------------------------------------------------------------
# resolve_install_spec 全链
# ---------------------------------------------------------------------------

def test_resolve_l1_cache_hit_no_ai(monkeypatch, tmp_path):
    _cache_dir(monkeypatch, tmp_path)
    installer.cache_store(_spec(name="cached-mcp", invoke_hint="cached"))

    def boom(p):
        raise AssertionError("不该调 AI")

    res = installer.resolve_install_spec("cached-mcp", allow_ai=True, chat_fn=boom)
    assert res.ok is True
    assert res.provenance == "cache"


def test_resolve_l2_catalog_hit(monkeypatch, tmp_path):
    _cache_dir(monkeypatch, tmp_path)
    res = installer.resolve_install_spec("context7", allow_ai=False)
    assert res.ok is True
    assert res.provenance == "catalog"


def test_resolve_ai_disabled_returns_fail(monkeypatch, tmp_path):
    _cache_dir(monkeypatch, tmp_path)
    res = installer.resolve_install_spec("不在目录里的", allow_ai=False)
    assert res.ok is False
    assert "ai" in res.reason.lower()


def test_resolve_ai_no_repo_returns_fail(monkeypatch, tmp_path):
    _cache_dir(monkeypatch, tmp_path)
    res = installer.resolve_install_spec("ghost", allow_ai=True, chat_fn=lambda p: "")
    assert res.ok is False
    assert "仓库" in res.reason


def test_resolve_full_ai_chain_verified_cached(monkeypatch, tmp_path):
    _cache_dir(monkeypatch, tmp_path)
    _patch_github(monkeypatch, files=["README.md"])
    _ok_run(monkeypatch)
    chat = lambda p: (  # noqa: E731
        '{"name":"new-mcp","command":"npx","args":["-y","new-mcp"],"invoke_hint":"新工具"}'
    )
    res = installer.resolve_install_spec(
        "new-mcp", repo="o/new-mcp", allow_ai=True, chat_fn=chat, has_tty=False
    )
    assert res.ok is True
    assert res.provenance == "ai"
    assert res.spec.verify_ok is True
    # 已入缓存
    cached = installer.cache_lookup("new-mcp")
    assert cached is not None
    assert cached.provenance == "cache"


def test_resolve_ai_skip_trial_not_cached(monkeypatch, tmp_path):
    _cache_dir(monkeypatch, tmp_path)
    _patch_github(monkeypatch, files=["README.md"])
    chat = lambda p: (  # noqa: E731
        '{"name":"sk-mcp","command":"npx","args":["-y","sk-mcp"],"invoke_hint":"x"}'
    )
    res = installer.resolve_install_spec(
        "sk-mcp", repo="o/sk-mcp", allow_ai=True, chat_fn=chat, skip_trial=True, has_tty=False
    )
    assert res.ok is True
    assert res.provenance == "ai_unverified"
    assert res.spec.verify_ok is False
    # 跳过试跑 → 不入缓存
    assert installer.cache_lookup("sk-mcp") is None


def test_resolve_ai_missing_cred_headless_skipped(monkeypatch, tmp_path):
    _cache_dir(monkeypatch, tmp_path)
    _patch_github(monkeypatch, files=["README.md"])
    _ok_run(monkeypatch)
    chat = lambda p: (  # noqa: E731
        '{"name":"cred-mcp","command":"npx","args":["-y","cred-mcp"],"credential_env":["MY_KEY"]}'
    )
    res = installer.resolve_install_spec(
        "cred-mcp", repo="o/cred-mcp", allow_ai=True, chat_fn=chat, has_tty=False
    )
    assert res.ok is True
    assert res.missing == ["MY_KEY"]  # headless 填不了
    assert res.filled == {}
    # 仍入缓存（装法本身验证过了）
    assert installer.cache_lookup("cred-mcp") is not None


def test_resolve_ai_missing_cred_with_prompt_fn_filled(monkeypatch, tmp_path):
    _cache_dir(monkeypatch, tmp_path)
    _patch_github(monkeypatch, files=["README.md"])
    _ok_run(monkeypatch)
    chat = lambda p: (  # noqa: E731
        '{"name":"cred2","command":"npx","args":["-y","cred2"],"credential_env":["MY_KEY"]}'
    )
    res = installer.resolve_install_spec(
        "cred2", repo="o/cred2", allow_ai=True, chat_fn=chat, prompt_fn=lambda v: "secret-val"
    )
    assert res.ok is True
    assert res.filled == {"MY_KEY": "secret-val"}
    assert res.missing == []  # 已补全


def test_resolve_verify_fail_returns_unresolved(monkeypatch, tmp_path):
    _cache_dir(monkeypatch, tmp_path)
    _patch_github(monkeypatch, files=["README.md"])

    def fake_run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, b"", b"npm ERR 404 not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    chat = lambda p: '{"name":"bad","command":"npx","args":["-y","bad"]}'  # noqa: E731
    res = installer.resolve_install_spec(
        "bad", repo="o/bad", allow_ai=True, chat_fn=chat, has_tty=False
    )
    assert res.ok is False
    assert "试跑" in res.reason
    assert installer.cache_lookup("bad") is None  # 没入缓存
