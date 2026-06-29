"""install 包的纯决策/解析逻辑：凭证判定、args 占位替换、MCP server 配置构造、依赖装法探测。"""

from __future__ import annotations

import os
from pathlib import Path


def _credentials_configured(item: dict) -> bool:
    """needs_credentials 的 MCP 是否已在环境里配好凭证（不替用户造凭证）。

    credential_env 形如 ["GITHUB_PERSONAL_ACCESS_TOKEN"]；全在 os.environ 里才算配好。
    无 credential_env 或非 needs_credentials → 视为无需凭证（True，可装）。
    """
    cred = item.get("credential_env") or []
    if not cred:
        return True
    return all(os.environ.get(k) for k in cred)


def _resolve_args(mcp: dict) -> tuple[list[str], bool]:
    """解析 args 里的 <DIRS> 占位符（needs_config），默认填 cwd+home。

    返回 (resolved_args, substituted_dirs)。其它 <…> 占位符不在本函数替换
    （由调用方 _has_unresolved_placeholder 兜底判跳过，避免注册坏服务器）。
    """
    args = [str(a) for a in (mcp.get("args") or [])]
    default_dirs = [str(Path.cwd()), str(Path.home())]
    sub = False
    out: list[str] = []
    for a in args:
        if a.strip().lower() == "<dirs>":
            # 整个 arg 就是 <DIRS> → 展开成多个独立目录参数
            # （filesystem server 要求每个允许目录各占一个 argv，连成带空格的单串会注册成坏服务器）
            out.extend(default_dirs)
            sub = True
        elif "<dirs>" in a.lower():
            # <DIRS> 仅作为子串嵌在更大字符串里 → 退化为空格连接替换
            a = a.replace("<DIRS>", " ".join(default_dirs)).replace(
                "<dirs>", " ".join(default_dirs)
            )
            sub = True
            out.append(a)
        else:
            out.append(a)
    return out, sub


def _has_unresolved_placeholder(resolved_args: list[str]) -> bool:
    """<DIRS> 已替换后，args 里若仍含 <…> 占位 → 不能装（needs_config 未解析），跳过。"""
    return any("<" in a and ">" in a for a in resolved_args)


def _inject_env(item: dict) -> dict:
    """收集 credential_env / env_template 里 os.environ 真有的键值（空占位不注入）。"""
    keys = list(item.get("credential_env") or []) + list((item.get("env_template") or {}).keys())
    return {k: os.environ[k] for k in keys if os.environ.get(k)}


def _mcp_server_config(item: dict, resolved_args: list[str]) -> dict:
    """构造要注册的 MCP server 配置（与 ~/.claude.json mcpServers 条目同构）。

    stdio：{command, args, env(仅注入已配置凭证)}；http/sse：{type, url, headers}。
    """
    mcp = item.get("mcp") or {}
    transport = (mcp.get("transport") or "stdio").lower()
    if transport in ("http", "sse"):
        server = {"type": transport, "url": mcp.get("url", "")}
        if mcp.get("headers"):
            server["headers"] = mcp["headers"]
        return server
    server = {"command": mcp.get("command", "")}
    if resolved_args:
        server["args"] = list(resolved_args)
    env_inj = _inject_env(item)
    if env_inj:
        server["env"] = env_inj
    return server


def _detect_deps_method(clone_dir: Path) -> str:
    """探测克隆目录里的依赖清单类型，决定装依赖走哪条路。

    pip 系（requirements.txt / pyproject.toml）走 ``python -m pip``；npm 系（package.json）
    走 ``npm install``；都没有返回 none（克隆已成功，依赖可后补）。
    """
    if (clone_dir / "requirements.txt").exists():
        return "pip-requirements"
    if (clone_dir / "pyproject.toml").exists():
        return "pip-pyproject"
    if (clone_dir / "package.json").exists():
        return "npm"
    return "none"
