"""install.mcp_toml 文本级段替换工具测试（纯字符串运算，不读写磁盘）。"""

from __future__ import annotations

# ---------- _toml_escape_string ----------


def test_escape_string_plain():
    from skillbrew.install.mcp_toml import _toml_escape_string

    assert _toml_escape_string("hello") == '"hello"'
    assert _toml_escape_string("") == '""'


def test_escape_string_special_chars():
    from skillbrew.install.mcp_toml import _toml_escape_string

    s = 'a\\b"c\nd\re\tf\x01g'
    out = _toml_escape_string(s)
    assert out.startswith('"') and out.endswith('"')
    assert "\\\\" in out
    assert '\\"' in out
    assert "\\n" in out
    assert "\\r" in out
    assert "\\t" in out
    assert "\\u0001" in out


# ---------- _toml_escape_bare_key ----------


def test_escape_bare_key_identifier():
    from skillbrew.install.mcp_toml import _toml_escape_bare_key

    assert _toml_escape_bare_key("foo") == "foo"
    assert _toml_escape_bare_key("foo_bar") == "foo_bar"
    assert _toml_escape_bare_key("npx_mcp") == "npx_mcp"


def test_escape_bare_key_resorts_to_quoted():
    from skillbrew.install.mcp_toml import _toml_escape_bare_key

    # 含非 bare 字符 → 引号包
    assert _toml_escape_bare_key("foo-bar").startswith('"')
    assert _toml_escape_bare_key("@modelcontextprotocol/server-filesystem").startswith('"')
    assert _toml_escape_bare_key("").startswith('"')


# ---------- _toml_render_mcp_server ----------


def test_render_stdio_command_only():
    from skillbrew.install.mcp_toml import _toml_render_mcp_server

    block = _toml_render_mcp_server("my_mcp", {"command": "npx"})
    assert "[mcp_servers.my_mcp]" in block
    assert 'command = "npx"' in block
    assert "args =" not in block
    assert block.endswith("\n")


def test_render_stdio_with_args_and_env():
    from skillbrew.install.mcp_toml import _toml_render_mcp_server

    block = _toml_render_mcp_server(
        "fs_mcp",
        {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            "env": {"FOO": "bar", "X": "1"},
        },
    )
    assert "[mcp_servers.fs_mcp]" in block
    assert 'command = "npx"' in block
    assert "args = [" in block
    assert '"-y"' in block
    assert '"@modelcontextprotocol/server-filesystem"' in block
    assert '"' + "/tmp" + '"' in block
    # env 子表
    assert "[mcp_servers.fs_mcp.env]" in block
    assert "FOO = " in block
    assert '"bar"' in block


def test_render_http_url():
    from skillbrew.install.mcp_toml import _toml_render_mcp_server

    block = _toml_render_mcp_server(
        "remote",
        {
            "type": "http",
            "url": "https://example.com/mcp",
            "bearer_token_env_var": "MY_TOKEN",
            "headers": {"X-Api": "v1"},
        },
    )
    assert "[mcp_servers.remote]" in block
    assert 'url = "https://example.com/mcp"' in block
    assert 'bearer_token_env_var = "MY_TOKEN"' in block
    assert "http_headers = {" in block
    # stdio 字段不出现
    assert "command =" not in block
    assert "args =" not in block


def test_render_quoted_name():
    """非 bare key 的 server 名渲染后 header 用引号 key。"""
    from skillbrew.install.mcp_toml import _toml_render_mcp_server

    block = _toml_render_mcp_server("@modelcontextprotocol/server-filesystem", {"command": "npx"})
    # 含引号的 header
    assert "[mcp_servers." in block
    assert '"@modelcontextprotocol/server-filesystem"' in block


# ---------- _toml_replace_mcp_server ----------


def test_replace_append_when_absent():
    """文件里还没有该 server 段：追加到末尾。"""
    from skillbrew.install.mcp_toml import _toml_replace_mcp_server

    text = "# 原来的配置\n[other]\nfoo = 1\n"
    block = '[mcp_servers.new_one]\ncommand = "x"\n'
    out = _toml_replace_mcp_server(text, "new_one", block)
    assert out.count("[mcp_servers.new_one]") == 1
    assert out.endswith(block)
    assert "[other]" in out  # 其它段保留


def test_replace_existing_server_block():
    """已存在时：替换掉原段（含 .env 子表），其它段不动。"""
    from skillbrew.install.mcp_toml import _toml_replace_mcp_server

    text = (
        "[mcp_servers.a]\n"
        'command = "old"\n'
        "\n"
        "[mcp_servers.a.env]\n"
        'X = "1"\n'
        "\n"
        "[mcp_servers.b]\n"
        'command = "keep"\n'
    )
    new_block = '[mcp_servers.a]\ncommand = "new"\nargs = ["x"]\n'
    out = _toml_replace_mcp_server(text, "a", new_block)
    assert 'command = "old"' not in out
    assert 'X = "1"' not in out  # 旧 env 子表被清掉
    assert 'command = "new"' in out
    assert 'args = ["x"]' in out
    assert 'command = "keep"' in out  # b 没动
    assert out.count("[mcp_servers.a]") == 1


def test_replace_preserves_comments_and_other_sections():
    """替换不吞掉其它段/注释/空白。"""
    from skillbrew.install.mcp_toml import _toml_replace_mcp_server

    text = '# top comment\n[model]\nprovider = "deepseek"\n\n[extra]\n'
    block = '[mcp_servers.s]\ncommand = "x"\n'
    out = _toml_replace_mcp_server(text, "s", block)
    assert "# top comment" in out
    assert "[model]" in out
    assert 'provider = "deepseek"' in out
    assert "[extra]" in out
    assert out.count("[mcp_servers.s]") == 1


def test_replace_dotted_name_quoted():
    """带点/特殊字符的名字（被 escape 成引号 key）也能正确识别替换。"""
    from skillbrew.install.mcp_toml import _toml_replace_mcp_server

    name = "@x/y"
    # 手动构造旧块（header 里 key 被引号包）
    from skillbrew.install.mcp_toml import _toml_escape_bare_key, _toml_render_mcp_server

    escaped = _toml_escape_bare_key(name)
    old = f'[mcp_servers.{escaped}]\ncommand = "old"\n'
    text = "[other]\na = 1\n\n" + old
    new_block = _toml_render_mcp_server(name, {"command": "new"})
    out = _toml_replace_mcp_server(text, name, new_block)
    assert 'command = "old"' not in out
    assert 'command = "new"' in out


# ---------- _strip_toml_comment ----------


def test_strip_toml_comment_basic():
    from skillbrew.install.mcp_toml import _strip_toml_comment

    assert _strip_toml_comment("1") == "1"
    assert _strip_toml_comment("1 # hi") == "1"
    assert _strip_toml_comment('"a # b" # outer') == '"a # b"'
    # 单引号内的 # 也保留
    assert _strip_toml_comment("'a # b' # outer") == "'a # b'"


def test_strip_toml_comment_no_comment():
    from skillbrew.install.mcp_toml import _strip_toml_comment

    assert _strip_toml_comment('"hello"') == '"hello"'
    assert _strip_toml_comment("  ") == "  "


# ---------- _toml_read_mcp_server 读写回环 ----------


def test_read_roundtrip_stdio():
    """render 出来的块，read 能把 command/args/env 读回。"""
    from skillbrew.install.mcp_toml import _toml_read_mcp_server, _toml_render_mcp_server

    server = {
        "command": "npx",
        "args": ["-y", "pkg", "/a/b"],
        "env": {"FOO": "bar", "N": "1"},
    }
    block = _toml_render_mcp_server("my_mcp", server)
    # 把块嵌进一个完整 TOML 文本
    text = "[other]\nx = 1\n\n" + block + "\n[next]\ny = 2\n"
    got = _toml_read_mcp_server(text, "my_mcp")
    assert got is not None
    assert got["command"] == "npx"
    assert got["args"] == ["-y", "pkg", "/a/b"]
    assert got["env"] == {"FOO": "bar", "N": "1"}
    # url 没有就不出
    assert "url" not in got


def test_read_roundtrip_http():
    from skillbrew.install.mcp_toml import _toml_read_mcp_server, _toml_render_mcp_server

    server = {"url": "https://example.com/mcp", "bearer_token_env_var": "T"}
    block = _toml_render_mcp_server("r", server)
    text = block
    got = _toml_read_mcp_server(text, "r")
    assert got is not None
    assert got["url"] == "https://example.com/mcp"
    assert got["bearer_token_env_var"] == "T"


def test_read_missing_server_returns_none():
    from skillbrew.install.mcp_toml import _toml_read_mcp_server

    assert _toml_read_mcp_server("[other]\na=1\n", "not_there") is None


def test_read_skips_comments_and_garbage():
    """段里有注释/垃圾行/无等号行被跳过，不出错。"""
    from skillbrew.install.mcp_toml import _toml_read_mcp_server

    text = '[mcp_servers.s]\n# a comment\ncommand = "x"\ngarbage-no-eq\nargs = ["a"]\n'
    got = _toml_read_mcp_server(text, "s")
    assert got is not None
    assert got["command"] == "x"
    assert got["args"] == ["a"]


# ---------- 端到端：replace 写进去再 read 回来 ----------


def test_replace_then_read_preserves_other_blocks():
    """先 replace 两个 server，再分别 read，互不干扰。"""
    from skillbrew.install.mcp_toml import (
        _toml_read_mcp_server,
        _toml_render_mcp_server,
        _toml_replace_mcp_server,
    )

    text = ""
    a_block = _toml_render_mcp_server("a", {"command": "ca"})
    b_block = _toml_render_mcp_server("b", {"command": "cb", "args": ["x"]})
    text = _toml_replace_mcp_server(text, "a", a_block)
    text = _toml_replace_mcp_server(text, "b", b_block)

    ga = _toml_read_mcp_server(text, "a")
    gb = _toml_read_mcp_server(text, "b")
    assert ga["command"] == "ca"
    assert gb["command"] == "cb"
    assert gb["args"] == ["x"]

    # 更新 a
    a2 = _toml_render_mcp_server("a", {"command": "ca2", "args": ["y"]})
    text = _toml_replace_mcp_server(text, "a", a2)
    ga2 = _toml_read_mcp_server(text, "a")
    gb2 = _toml_read_mcp_server(text, "b")
    assert ga2["command"] == "ca2"
    assert ga2["args"] == ["y"]
    assert gb2["command"] == "cb"  # b 不受影响
