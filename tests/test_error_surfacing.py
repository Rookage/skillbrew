"""零 token 自测：异常不再静默吞——CLI traceback / 库级 warnings.warn + 损坏文件 .bak 备份 (#15)。

不连网、不真调 LLM、不碰真实 ~/.claude.json。覆盖：
  ① 项目级 .mcp.json 损坏 → warning + .bak 备份 + 从空重建成功
  ② installer._atomic_write_json 含密钥指纹 → warning + 文件未被改写
  ③ verify.enrich_with_frontmatter 网络失败 → warning + fetch_error 字段落位
  ④ cli 顶层 cmd_* 走 except 时 traceback.print_exc 被调用（monkeypatch sys.stderr 捕获）
"""

from __future__ import annotations

import json
import warnings
from unittest import mock

from skillbrew import installer, verify

# ---------- ① 项目级 .mcp.json 损坏：warn + .bak 备份 + 重建 ----------


def test_corrupt_project_mcp_json_warns_and_backs_up(tmp_path, monkeypatch):
    """损坏的 .mcp.json → 原字节备份到 .mcp.json.bak；新文件可解析、写入成功；发 warning。"""
    monkeypatch.chdir(tmp_path)
    pm = tmp_path / ".mcp.json"
    corrupt_bytes = b"{this is not valid json !!!"
    pm.write_bytes(corrupt_bytes)

    # 构造一个最小可写的 item，直接调 _install_mcp_json_merge project 分支
    from skillbrew.install import _install_mcp_json_merge

    item = {
        "name": "fake-mcp",
        "mcp": {"command": "echo", "args": ["hi"]},
    }
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result = _install_mcp_json_merge(
            name="fake-mcp",
            item=item,
            scope="project",
            transport="stdio",
            resolved_args=["hi"],
        )

    # 新文件可解析
    new_data = json.loads(pm.read_text(encoding="utf-8"))
    assert "fake-mcp" in new_data.get("mcpServers", {})
    # .bak 存的是损坏的原字节（数据不丢）
    bak = pm.with_suffix(".json.bak")
    assert bak.exists()
    assert bak.read_bytes() == corrupt_bytes
    # 有 warning 指向「损坏」
    msgs = [str(x.message) for x in w]
    assert any("损坏" in m and ".mcp.json" in m for m in msgs), msgs
    assert result["registered_via"] == "json-merge"


# ---------- ② installer._atomic_write_json D14 指纹守卫：warn + 不写 ----------


def test_atomic_write_json_skips_on_key_fingerprint(tmp_path):
    """缓存 dict 里含 sk- 指纹 → 不写文件、发 warning。"""
    target = tmp_path / "install_cache.json"
    target.write_text("{}", encoding="utf-8")  # 预先放占位内容，验证未被改写
    original = target.read_bytes()

    bad_obj = {"some_mcp": {"env": {"OPENAI_API_KEY": "sk-abc123REALKEY"}}}
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        installer._atomic_write_json(target, bad_obj)

    # 原文件字节未变
    assert target.read_bytes() == original
    msgs = [str(x.message) for x in w]
    assert any("D14" in m and "指纹" in m for m in msgs), msgs


def test_atomic_write_json_writes_clean_obj(tmp_path):
    """干净 dict 正常落盘、无 warning。"""
    target = tmp_path / "clean.json"
    clean = {"ok": True, "env_template": {"OPENAI_API_KEY": ""}}  # 值恒空（D14 卫生器输出）
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        installer._atomic_write_json(target, clean)
    assert target.exists()
    assert json.loads(target.read_text(encoding="utf-8")) == clean
    assert not [x for x in w if "D14" in str(x.message)]


# ---------- ③ verify.enrich_with_frontmatter 网络失败：warn + fetch_error ----------


def test_enrich_with_frontmatter_warns_on_fetch_error(monkeypatch):
    """_raw_text 抛异常 → 该 skill display_name=name、description 空、fetch_error 截断到 200 字符；发 warning。"""
    # 准备一个最小的 skills 列表（字段名要和 verify._scan_skill_dirs 输出一致：sk_md_path）
    skills = [
        {
            "name": "broken-skill",
            "owner": "o",
            "repo": "r",
            "branch": "main",
            "sk_md_path": "SKILL.md",
        }
    ]

    def fake_raw_text(url, timeout=10):
        raise RuntimeError("simulated network timeout")

    monkeypatch.setattr(verify, "_raw_text", fake_raw_text)

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        verify.enrich_with_frontmatter(
            owner="o",
            repo="r",
            branch="main",
            skills=skills,
            on_progress=None,
        )

    s = skills[0]
    assert s.get("display_name") == "broken-skill"
    assert s.get("description") == ""
    assert "fetch_error" in s
    assert s["fetch_error"].startswith("simulated network timeout")
    assert len(s["fetch_error"]) <= 200
    msgs = [str(x.message) for x in w]
    assert any("SKILL.md 获取失败" in m for m in msgs), msgs


# ---------- ④ cli 顶层 except 走 traceback.print_exc（行为级验证） ----------


def test_cli_install_except_prints_traceback(tmp_path, monkeypatch, capsys):
    """cmd_install 子路径抛异常 → 走 except 分支调用 traceback.print_exc（栈打到 stderr），再打 [FAIL]。

    策略：mock traceback.print_exc 验证 except 分支被触发；同时验证 stderr 有栈、stdout 有 [FAIL]。
    cmd_install 内部 `from . import install as install_mod` 取的是模块，
    所以直接替换 skillbrew.install.install 为抛异常的函数。
    """
    import importlib

    import skillbrew.cli as cli

    importlib.reload(cli)  # 确保新 import traceback/warnings 生效

    assert hasattr(cli, "traceback"), "cli.py 应 import traceback 供顶层 except 使用"

    import skillbrew.install as install_mod
    from skillbrew import cli as cli_mod

    # 造最小 src 目录，让 cmd_install 的 exists() 检查过
    src = tmp_path / "src"
    src.mkdir()
    (src / "install_list.json").write_text("{}", encoding="utf-8")
    (src / "dedup.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(cli_mod, "load_config", lambda: object())
    monkeypatch.setattr(cli_mod, "_resolve_source", lambda cfg, s: src)

    class _Args:
        source = str(src)
        approve = False
        target_dir = None
        include_deprecated = False
        ai_infer = False
        no_trial = False
        refresh_cache = False

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(install_mod, "install", _boom)

    # 用 mock.patch 监听 traceback.print_exc 有没有被调到
    with mock.patch.object(cli.traceback, "print_exc") as m_pe:
        rc = cli_mod.cmd_install(_Args())

    # 返回码应为非 0（失败）
    assert rc != 0, f"cmd_install 异常路径应返回非零退出码，got {rc}"
    m_pe.assert_called_once()

    # 再跑一次不 mock traceback，验证 stderr 真能拿到栈（capsys 捕获 pytest 级 stdout/stderr）
    monkeypatch.setattr(install_mod, "install", _boom)  # 重置
    cli_mod.cmd_install(_Args())
    captured = capsys.readouterr()
    assert "Traceback (most recent call last)" in captured.err, (
        f"stderr 缺 traceback: {captured.err!r}"
    )
    assert "RuntimeError: boom" in captured.err
    assert "[FAIL]" in captured.out
