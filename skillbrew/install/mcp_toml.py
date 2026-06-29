"""install 包的 Codex TOML MCP 注册文本级段替换工具。

核心：只切 ``[mcp_servers.<name>]`` 段替换，文件其它 section/注释/空白原样保留。
这是 tomlkit 等通用 TOML 库做不到的——它们 dumps 时会重规范化整份文档。
"""

from __future__ import annotations

_MCP_SERVER_HEADER_RE = None  # 占位，运行时用行级切分，不做正则


def _toml_escape_string(s: str) -> str:
    """把 Python 字符串转成 TOML 基本字符串字面量（"..." 内）。仅转义必须转义的字符。"""
    out = ['"']
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _toml_escape_bare_key(k: str) -> str:
    """若 key 含非 bare-key 字符则用引号包，否则原样返回。"""
    if k.isidentifier() and k.lower() == k and not k.startswith("_"):
        if not k[0].isdigit():
            return k
    if k and (k[0].isalpha() or k[0] == "_") and all(c.isalnum() or c == "_" for c in k):
        return k
    return _toml_escape_string(k)


def _toml_render_mcp_server(name: str, server: dict) -> str:
    """把单个 MCP server 配置渲染成 Codex config.toml 的 [mcp_servers.<name>] 段。

    字段：command（必填，stdio）/ args（可选字符串数组）/ env（可选字符串→字符串键值表）。
    http/sse 类：url（必要时附带 bearer_token_env_var / http_headers）—— 用 TOML inline table。
    参考 Context7 文档中的格式（codex-rs core/src/config/config_tests.rs）。
    """
    lines = [f"[mcp_servers.{_toml_escape_bare_key(name)}]"]

    # http / sse
    if server.get("type") in ("http", "sse") or "url" in server:
        lines.append(f"url = {_toml_escape_string(server.get('url', ''))}")
        if server.get("bearer_token_env_var"):
            lines.append(
                f"bearer_token_env_var = {_toml_escape_string(server['bearer_token_env_var'])}"
            )
        if server.get("headers"):
            headers = ", ".join(
                f"{_toml_escape_string(k)} = {_toml_escape_string(v)}"
                for k, v in server["headers"].items()
            )
            lines.append(f"http_headers = {{ {headers} }}")
        return "\n".join(lines) + "\n"

    # stdio
    if server.get("command"):
        lines.append(f"command = {_toml_escape_string(server['command'])}")
    args = server.get("args") or []
    if args:
        rendered_args = ", ".join(_toml_escape_string(a) for a in args)
        lines.append(f"args = [{rendered_args}]")
    env = server.get("env") or {}
    if env:
        # 用子表 [mcp_servers.<name>.env]（与官方测试用例一致），而不是 inline table
        lines.append("")
        lines.append(f"[mcp_servers.{_toml_escape_bare_key(name)}.env]")
        for k, v in env.items():
            lines.append(f"{_toml_escape_bare_key(k)} = {_toml_escape_string(str(v))}")
    return "\n".join(lines) + "\n"


def _toml_replace_mcp_server(text: str, name: str, block: str) -> str:
    """在 TOML 文本里替换/追加指定 mcp_servers.<name> 段。

    采用行级切分，不做全量 TOML 解析，保留用户其它 section、注释、空白原样。
    段识别：以 ``[mcp_servers.<name>]`` 或 ``[mcp_servers.<name>.xxx]`` 开头的行
    视为该 server 的块，直到下一个顶层 ``[xxx]``（无缩进的 [ 开头行）为止。
    """
    escaped = _toml_escape_bare_key(name)
    header = f"[mcp_servers.{escaped}]"
    sub_prefix = f"[mcp_servers.{escaped}."

    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    replaced = False
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        # 新段起始（行首就是 [，无缩进），且是目标 server
        if stripped.startswith("[") and not line[:1].isspace():
            body = stripped.strip()
            is_target = False
            if body == header:
                is_target = True
            elif body.startswith(sub_prefix):
                is_target = True
            if is_target:
                # 跳过目标 server 的原有所有行（含 .env / .env.xxx 等任意子表），
                # 直到遇到一个既不是主 header、也不属于当前 server 的子表的顶层 [ 段 或 EOF
                i += 1
                while i < len(lines):
                    nxt = lines[i]
                    nxt_stripped = nxt.lstrip()
                    if nxt_stripped.startswith("[") and not nxt[:1].isspace():
                        nxt_body = nxt_stripped.strip()
                        if nxt_body == header or nxt_body.startswith(sub_prefix):
                            i += 1
                            continue
                        break
                    i += 1
                # 写新块（保证前后有空行，视觉上干净；不重复加空行以免每次 append 都变多）
                if out and not out[-1].endswith("\n\n"):
                    if out[-1].strip():
                        out.append("\n")
                out.append(block)
                replaced = True
                continue
        out.append(line)
        i += 1

    if not replaced:
        # 文件末尾追加：保证最后有换行
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        if out and out[-1] != "\n":
            out.append("\n")
        out.append(block)
    return "".join(out)


def _strip_toml_comment(v: str) -> str:
    """去掉 TOML 值尾部的 # 行注释，保留引号内的 #。"""
    in_str = False
    quote = ""
    i = 0
    while i < len(v):
        ch = v[i]
        if in_str:
            if ch == "\\" and i + 1 < len(v):
                i += 2
                continue
            if ch == quote:
                in_str = False
        else:
            if ch in ('"', "'"):
                in_str = True
                quote = ch
            elif ch == "#":
                return v[:i].rstrip()
        i += 1
    return v


def _toml_read_mcp_server(text: str, name: str) -> dict | None:
    """在 TOML 文本里把 [mcp_servers.<name>] 段（含 .env 子表）读回 dict，用于写后校验。

    只支持我们自己写出的字段：command(str) / args(list[str]) / env(dict[str,str]) / url(str)。
    是最小可用解析器——只要能把自己写的读回来就行，通用 TOML 不承诺解析完整。
    """
    import ast

    escaped = _toml_escape_bare_key(name)
    header = f"[mcp_servers.{escaped}]"
    env_header = f"[mcp_servers.{escaped}.env]"

    lines = text.splitlines()
    n = len(lines)

    def _section_start(h: str) -> int:
        for idx, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith(h) and s.endswith("]") and s == h:
                return idx
        return -1

    i_main = _section_start(header)
    if i_main < 0:
        return None

    def _section_end(start: int) -> int:
        j = start + 1
        while j < n:
            s = lines[j].strip()
            if s.startswith("[") and not lines[j][:1].isspace():
                return j
            j += 1
        return j

    end_main = _section_end(i_main)
    main_block = lines[i_main + 1 : end_main]

    i_env = _section_start(env_header)
    env_block: list[str] = []
    if i_env >= 0:
        end_env = _section_end(i_env)
        env_block = lines[i_env + 1 : end_env]

    result: dict = {}
    for raw in main_block:
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("["):
            break
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip()
        v_no_comment = _strip_toml_comment(v)
        try:
            py_v = v_no_comment
            val = ast.literal_eval(py_v)
        except Exception:  # noqa: BLE001
            continue
        result[k] = val

    env: dict = {}
    for raw in env_block:
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("["):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        k = k.strip()
        v = v.strip()
        v_no_comment = _strip_toml_comment(v)
        try:
            val = ast.literal_eval(v_no_comment)
        except Exception:  # noqa: BLE001
            continue
        if isinstance(val, str):
            env[k] = val
    if env:
        result["env"] = env
    return result
