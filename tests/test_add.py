"""`add` 子命令 + register_mcp 通用注册原语测试（issue #27 Phase 2）。

分两层：
- register_mcp（install 层原语）：dry-run 预览脱敏 / approve 真写 + 台账 / 入参校验 / 归一化。
- cmd_add（CLI 薄壳）：参数推断、--from smithery 远程/本地分流、dry-run vs --approve、错误码。

隔离：approve 真写用 env 三件套（SKILLBREW_RUNTIME=claude + SKILLBREW_CLAUDE_JSON=tmp +
monkeypatch registry.DB_PATH=tmp），不碰用户真实 ~/.claude.json / 台账。dry-run 不落盘。
"""

from __future__ import annotations

import argparse
import json

import pytest

from skillbrew import install as install_mod
from skillbrew import marketplace, registry
from skillbrew.cli.commands.add import _parse_header, cmd_add
from skillbrew.install.executor import _mask_server, _normalize_transport
from skillbrew.marketplace import ServerDetail

# 无害常量（fresh-clone 复扫安全：占位值不构成真实 key 指纹）
_URL = "https://mcp.example.test/mcp"
_HDR_VAL = "dummy-token-value"  # 不是真 key 指纹，仅占位


def _ns(**kw) -> argparse.Namespace:
    """构造 cmd_add 用的 Namespace（缺省与 parser 默认一致：arg/env/header/transport=None）。"""
    base = dict(
        name="",
        url=None,
        command=None,
        arg=None,
        env=None,
        header=None,
        transport=None,
        scope="user",
        from_smithery=None,
        approve=False,
    )
    base.update(kw)
    return argparse.Namespace(**base)


# ==================== 纯函数：_normalize_transport / _mask_server / _parse_header ====================


def test_normalize_transport_variants():
    """http/https/streamable-http → http；sse → sse；其余（含空/None）→ stdio。"""
    f = _normalize_transport
    assert f("http") == "http"
    assert f("HTTPS") == "http"
    assert f("streamable-http") == "http"
    assert f("streamable_http") == "http"
    assert f("sse") == "sse"
    assert f("SSE") == "sse"
    assert f("stdio") == "stdio"
    assert f("") == "stdio"
    assert f(None) == "stdio"
    assert f("weird") == "stdio"


def test_mask_server_redacts_env_headers():
    """env/headers 的值换 <KEY>，其它键原样；不改动原对象。"""
    s = {"command": "npx", "args": ["a"], "env": {"K1": "secret1"}, "headers": {"H1": "secret2"}}
    m = _mask_server(s)
    assert m["command"] == "npx"
    assert m["args"] == ["a"]
    assert m["env"] == {"K1": "<K1>"}
    assert m["headers"] == {"H1": "<H1>"}
    assert s["env"]["K1"] == "secret1"  # 原对象不被改


def test_parse_header_valid():
    assert _parse_header("X-Token: abc") == ("X-Token", "abc")
    assert _parse_header("k:v") == ("k", "v")  # 无空格


def test_parse_header_missing_colon():
    with pytest.raises(ValueError):
        _parse_header("no-colon-here")


# ==================== register_mcp：入参校验 ====================


def test_register_mcp_requires_name():
    with pytest.raises(RuntimeError):
        install_mod.register_mcp("")


def test_register_mcp_http_requires_url():
    with pytest.raises(RuntimeError):
        install_mod.register_mcp("x", transport="http")


def test_register_mcp_stdio_requires_command():
    with pytest.raises(RuntimeError):
        install_mod.register_mcp("x", transport="stdio")


def test_register_mcp_stdio_unresolved_placeholder():
    """args 含非 <DIRS> 的 <…> 占位 → 拒绝注册（防注册坏服务器）。"""
    with pytest.raises(RuntimeError):
        install_mod.register_mcp("x", transport="stdio", command="npx", args=["<unresolved>"])


# ==================== register_mcp：dry-run（不落盘、不登台账、预览脱敏） ====================


def test_register_mcp_dryrun_http():
    r = install_mod.register_mcp("rem", transport="http", url=_URL, headers={"X-T": _HDR_VAL})
    assert r["approve"] is False
    assert r["transport"] == "http"
    assert r["path"] == "(dry-run 未落盘)"
    srv = r["server"]
    assert srv["type"] == "http"
    assert srv["url"] == _URL
    assert srv["headers"] == {"X-T": "<X-T>"}  # 脱敏


def test_register_mcp_dryrun_stdio():
    r = install_mod.register_mcp("loc", transport="stdio", command="npx", args=["-y", "pkg"])
    assert r["approve"] is False
    assert r["transport"] == "stdio"
    srv = r["server"]
    assert srv["command"] == "npx"
    assert srv["args"] == ["-y", "pkg"]
    assert "env" not in srv  # 无 env_keys → 不注入


def test_register_mcp_dryrun_missing_env(monkeypatch):
    """声明了 env_keys 但 os.environ 没有 → missing_env 列出。"""
    monkeypatch.delenv("SKILLBREW_PROBE_KEY_Q", raising=False)
    r = install_mod.register_mcp(
        "svc", transport="stdio", command="npx", args=["-y", "pkg"],
        env_keys=["SKILLBREW_PROBE_KEY_Q"],
    )
    assert r["missing_env"] == ["SKILLBREW_PROBE_KEY_Q"]
    assert r["approve"] is False


def test_register_mcp_dryrun_env_present(monkeypatch):
    """env_keys 在 os.environ 有值 → missing_env 空，预览 env 脱敏成 <KEY>。"""
    monkeypatch.setenv("SKILLBREW_PROBE_KEY_P", "val")
    r = install_mod.register_mcp(
        "svc", transport="stdio", command="npx", args=["-y", "pkg"],
        env_keys=["SKILLBREW_PROBE_KEY_P"],
    )
    assert r["missing_env"] == []
    assert r["server"]["env"] == {"SKILLBREW_PROBE_KEY_P": "<SKILLBREW_PROBE_KEY_P>"}


# ==================== register_mcp：approve 真写（隔离 tmp） ====================


def _isolate(tmp_path, monkeypatch):
    """三件套隔离：claude 运行时 + 临时 claude.json + 临时台账 db。返回 (cj_path, db_path)。"""
    monkeypatch.setenv("SKILLBREW_RUNTIME", "claude")
    cj = tmp_path / "cj.json"
    monkeypatch.setenv("SKILLBREW_CLAUDE_JSON", str(cj))
    db = tmp_path / "reg.db"
    return cj, db


def test_register_mcp_approve_http(tmp_path, monkeypatch):
    cj, db = _isolate(tmp_path, monkeypatch)
    r = install_mod.register_mcp(
        "rem", transport="http", url=_URL, headers={"X-T": _HDR_VAL},
        scope="user", source="manual", approve=True, db_path=db,
    )
    assert r["approve"] is True
    assert r["registered_via"] == "json-merge"
    data = json.loads(cj.read_text(encoding="utf-8"))
    srv = data["mcpServers"]["rem"]
    assert srv["url"] == _URL
    assert srv["headers"]["X-T"] == _HDR_VAL  # 真值写入配置
    assert r["server"]["headers"]["X-T"] == "<X-T>"  # 返回预览仍脱敏
    # 台账已登记
    conn = registry.connect(db)
    assert conn.execute("SELECT 1 FROM skills WHERE name='rem' AND form='MCP'").fetchone()
    sess = conn.execute(
        "SELECT skills_added, skills_merged FROM install_sessions WHERE session_id LIKE 'add-rem-%'"
    ).fetchone()
    assert sess and sess["skills_added"] == 1 and sess["skills_merged"] == 0
    conn.close()


def test_register_mcp_approve_stdio(tmp_path, monkeypatch):
    cj, db = _isolate(tmp_path, monkeypatch)
    monkeypatch.setenv("SKILLBREW_PROBE_KEY_S", "val")
    r = install_mod.register_mcp(
        "loc", transport="stdio", command="npx", args=["-y", "pkg"],
        env_keys=["SKILLBREW_PROBE_KEY_S"], scope="user", approve=True, db_path=db,
    )
    assert r["approve"] is True
    data = json.loads(cj.read_text(encoding="utf-8"))
    srv = data["mcpServers"]["loc"]
    assert srv["command"] == "npx"
    assert srv["args"] == ["-y", "pkg"]
    assert srv["env"]["SKILLBREW_PROBE_KEY_S"] == "val"  # 真值写入
    assert r["server"]["env"]["SKILLBREW_PROBE_KEY_S"] == "<SKILLBREW_PROBE_KEY_S>"  # 预览脱敏


def test_register_mcp_approve_upserts_existing(tmp_path, monkeypatch):
    """同名二次 approve = upsert（不报唯一冲突，覆盖更新）。"""
    cj, db = _isolate(tmp_path, monkeypatch)
    install_mod.register_mcp("dup", transport="http", url=_URL, approve=True, db_path=db)
    install_mod.register_mcp("dup", transport="http", url="https://other.test/mcp",
                             approve=True, db_path=db)
    conn = registry.connect(db)
    rows = conn.execute("SELECT name FROM skills WHERE name='dup'").fetchall()
    assert len(rows) == 1  # 仍只有一行（upsert）
    conn.close()
    data = json.loads(cj.read_text(encoding="utf-8"))
    assert data["mcpServers"]["dup"]["url"] == "https://other.test/mcp"  # 覆盖成新 url


# ==================== cmd_add：CLI 薄壳 ====================


def test_parse_add_args_negflag():
    """argparse 层回归：值以 - 开头须用 --arg=VAL 等号形式（否则 argparse 把 -y 当选项报错）。"""
    from skillbrew.cli.parser import parse_args

    a = parse_args(["add", "x", "--command", "npx", "--arg=-y", "--arg", "pkg"])
    assert a.arg == ["-y", "pkg"]
    assert a.command == "npx"
    assert a.name == "x"


def test_cmd_add_no_mode_error(capsys):
    """没给 --url/--command/--from → 报错码 2。"""
    rc = cmd_add(_ns(name="foo"))
    assert rc == 2
    assert "[FAIL]" in capsys.readouterr().out


def test_cmd_add_dryrun_url(capsys):
    rc = cmd_add(_ns(name="rem", url=_URL))
    assert rc == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert _URL in out  # server 预览含 url
    assert "http" in out


def test_cmd_add_dryrun_command(capsys, monkeypatch):
    monkeypatch.delenv("SKILLBREW_PROBE_KEY_R", raising=False)
    rc = cmd_add(_ns(name="loc", command="npx", arg=["-y", "pkg"], env=["SKILLBREW_PROBE_KEY_R"]))
    assert rc == 0
    out = capsys.readouterr().out
    assert "stdio" in out
    assert "dry-run" in out


def test_cmd_add_bad_header(capsys):
    """-H 缺冒号 → 报错码 2。"""
    rc = cmd_add(_ns(name="rem", url=_URL, header=["no-colon"]))
    assert rc == 2
    assert "[FAIL]" in capsys.readouterr().out


def test_cmd_add_from_smithery_remote(capsys, monkeypatch):
    """--from smithery + 远程托管 → 自动取 deployment_url 走 http（dry-run）。"""
    detail = ServerDetail(
        qualified_name="github", display_name="GitHub", description="d",
        remote=True, deployment_url=_URL, transport="http",
        tool_count=3, prompt_count=0, resource_count=0,
        homepage="https://smithery.test/github", needs_config=False,
    )
    monkeypatch.setattr(marketplace, "info", lambda name: detail)
    rc = cmd_add(_ns(name="github", from_smithery="smithery"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "http" in out
    assert "dry-run" in out
    assert _URL in out


def test_cmd_add_from_smithery_local_stdio(capsys, monkeypatch):
    """--from smithery + 本地 stdio → 市场详情无装法，打印手动提示，不强制装。"""
    detail = ServerDetail(
        qualified_name="fs", display_name="FS", description="d",
        remote=False, deployment_url="", transport="stdio",
        tool_count=1, prompt_count=0, resource_count=0,
        homepage="https://example.test/fs", needs_config=True,
    )
    monkeypatch.setattr(marketplace, "info", lambda name: detail)
    rc = cmd_add(_ns(name="fs", from_smithery="smithery"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "本地 stdio" in out
    assert "skillbrew add" in out  # 给出手动装法示例
    assert "https://example.test/fs" in out  # needs_config 时附 homepage


def test_cmd_add_from_smithery_market_error(capsys, monkeypatch):
    """市场拉详情失败 → 报错码 2，不崩。"""
    def _boom(name):
        raise marketplace.MarketplaceError("network down")
    monkeypatch.setattr(marketplace, "info", _boom)
    rc = cmd_add(_ns(name="x", from_smithery="smithery"))
    assert rc == 2
    assert "[FAIL]" in capsys.readouterr().out


def test_cmd_add_approve_writes(tmp_path, monkeypatch, capsys):
    """CLI --approve 真写：配置落盘 + 台账登记 + [OK] 输出。"""
    cj, db = _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(registry, "DB_PATH", db)  # CLI 不传 db_path，走 registry.DB_PATH
    rc = cmd_add(_ns(name="myhttp", url=_URL, approve=True))
    assert rc == 0
    data = json.loads(cj.read_text(encoding="utf-8"))
    assert data["mcpServers"]["myhttp"]["url"] == _URL
    out = capsys.readouterr().out
    assert "[OK]" in out
    # 台账
    conn = registry.connect(db)
    assert conn.execute("SELECT 1 FROM skills WHERE name='myhttp' AND form='MCP'").fetchone()
    conn.close()
