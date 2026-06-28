"""MCP（模型上下文协议）服务器目录 —— brew-formula 模式（章程 D20）。

为什么硬编码目录而不是让 LLM 产 install_steps？
  plan 阶段 LLM 凭字幕臆造的安装命令（如 `npx @anthropic-ai/claude-code add-mcp
  playwright`）并不存在，照装必失败。MCP 的「包名/启动命令/scope/凭证」是确定性
  事实，用一张人工核实的 brew-formula 表替代不可靠的 LLM 推断，更稳、可审计。

本目录只覆盖「视频/报告里高频出现、官方有标准 npx 包」的 MCP。catalog miss 的
（如字幕里的 memos 无官方 MCP）由 verify 透传进 unresolved[]，交用户拍板（D19 先
判、D22 反黑箱），绝不臆造包装。

下游只读，不联网、不调 LLM。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class McpEntry:
    """一条 MCP 服务器的 brew-formula。

    name            规范名（注册时用的服务器名，如 sequential-thinking）
    transport       传输方式：stdio（本地子进程）/ http / sse
    command         启动命令（如 npx）
    args            命令参数（如 ["-y", "@playwright/mcp@latest"]）
    aliases         字幕/OCR 里可能的其它写法（如 "file system"、"contact7"），用于模糊匹配
    env_template    环境变量模板（值为空串，待填），如 {"GITHUB_PERSONAL_ACCESS_TOKEN": ""}
    repo            溯源仓库全名（owner/repo），无则 None
    url             主页/文档 URL，无则 None
    credential_env  必填凭证环境变量名（缺则装了不能立刻用），如 ["GITHUB_PERSONAL_ACCESS_TOKEN"]
    optional_credential_env  可选凭证环境变量名（有则更好，无也能跑），如 context7 的 CONTEXT7_API_KEY
    needs_config    是否需额外配置才能用（如 filesystem 要指定允许访问的目录）
    needs_runtime   是否需额外运行时/首跑下载（如 playwright 首跑下浏览器内核）
    post_install_steps  装完前必做的说明（D22「装完前必做」列取此）
    scope_hint      建议注册 scope（默认 user）
    invoke_hint     怎么调用它（台账/报告里给用户的提示）
    verified        是否经一手核实（brew-formula 表默认 True）
    """

    name: str
    command: str
    args: tuple[str, ...]
    invoke_hint: str
    transport: str = "stdio"
    aliases: tuple[str, ...] = ()
    env_template: dict[str, str] = field(default_factory=dict)
    repo: str | None = None
    url: str | None = None
    credential_env: tuple[str, ...] = ()
    optional_credential_env: tuple[str, ...] = ()
    needs_config: bool = False
    needs_runtime: bool = False
    post_install_steps: tuple[str, ...] = ()
    scope_hint: str = "user"
    verified: bool = True


# ---- 人工核实的标准 MCP 目录（6 条；memos 无官方包，故意不收录 → unresolved） ----
CATALOG: dict[str, McpEntry] = {
    "playwright": McpEntry(
        name="playwright",
        command="npx",
        args=("-y", "@playwright/mcp@latest"),
        aliases=("playwright-mcp", "microsoft/playwright-mcp", "playwrite", "playwrite mcp"),
        repo="microsoft/playwright-mcp",
        url="https://github.com/microsoft/playwright-mcp",
        needs_runtime=True,
        post_install_steps=("首次调用会自动下载浏览器内核（约 200MB），需联网",),
        invoke_hint="让 Claude 操作浏览器：打开网页、点击、填表、检查报错、跑前端流程",
    ),
    "filesystem": McpEntry(
        name="filesystem",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-filesystem", "<DIRS>"),
        aliases=("file system", "file system mcp", "filesystem mcp", "filesystem-mcp"),
        repo="modelcontextprotocol/servers",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem",
        needs_config=True,
        post_install_steps=(
            "args 里的 <DIRS> 必须替换为允许访问的真实目录（多个用空格），默认占位待改",
        ),
        invoke_hint="让 Claude 读写本地文件、理解项目结构、找入口/配置/分析依赖",
    ),
    "sequential-thinking": McpEntry(
        name="sequential-thinking",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-sequential-thinking"),
        aliases=("sequential thinking", "sequential thinking mcp", "sequentialthinking"),
        repo="modelcontextprotocol/servers",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/sequentialthinking",
        invoke_hint="复杂问题/Bug 排查：拆成推理链路，先确认现象再提假设再逐个排查",
    ),
    "context7": McpEntry(
        name="context7",
        command="npx",
        args=("-y", "@upstash/context7-mcp"),
        aliases=("contact7", "contact7 mcp", "context7 mcp"),
        repo="upstash/context7",
        url="https://github.com/upstash/context7",
        env_template={"CONTEXT7_API_KEY": ""},
        optional_credential_env=("CONTEXT7_API_KEY",),
        post_install_steps=("CONTEXT7_API_KEY 可选（无 key 也能查，有 key 额度更高）",),
        invoke_hint="写代码前先查最新官方文档（Next.js/React/Prisma/Supabase 等），防模型记忆过时",
    ),
    "github": McpEntry(
        name="github",
        command="npx",
        args=("-y", "@modelcontextprotocol/server-github"),
        aliases=("github mcp", "github-mcp"),
        repo="modelcontextprotocol/servers",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/github",
        env_template={"GITHUB_PERSONAL_ACCESS_TOKEN": ""},
        credential_env=("GITHUB_PERSONAL_ACCESS_TOKEN",),
        post_install_steps=(
            "必须在环境配 GITHUB_PERSONAL_ACCESS_TOKEN（GitHub PAT），否则装了调不通",
        ),
        invoke_hint="读 issue/PR/commit、理解协作上下文，基于 issue 改代码、总结变更、备 PR",
    ),
    "sqlite": McpEntry(
        name="sqlite",
        command="uvx",
        args=("mcp-server-sqlite", "--db-path", "<DB_PATH>"),
        aliases=("sqlite mcp", "mcp-server-sqlite", "sqlite server"),
        repo="modelcontextprotocol/servers",
        url="https://github.com/modelcontextprotocol/servers/tree/main/src/sqlite",
        needs_config=True,
        post_install_steps=(
            "args 里的 <DB_PATH> 必须替换为要访问的 .db 文件真实路径，默认占位待改；"
            "首次调用会通过 uvx 自动拉取 mcp-server-sqlite（需装 uv，pip install uv）",
        ),
        invoke_hint="让 Claude 直接查询 SQLite 数据库：跑 SELECT、理解表结构、做数据分析",
    ),
    # memos 故意不收录：字幕里的「memos」无官方 MCP 包。verify 会把它放进 unresolved[]，
    # 候选指向官方 @modelcontextprotocol/server-memory（知识图谱记忆），交用户定夺。
}


# 字幕/OCR 常见误记 → 规范名（在压成纯字母数字前先纠拼写）
_TYPO_FIX = {
    "contact7": "context7",
    "playwrite": "playwright",
}


def _normalize(name: str) -> str:
    """把字幕/OCR 里的 MCP 名称压成可比对的纯字母数字串。

    处理：去 microsoft/ 前缀、去 mcp/server 后缀词、压掉非字母数字（"file system"→"filesystem"）、
    修 contact7→context7、playwrite→playwright。返回值仅用于查 alias 索引，不是显示名。
    """
    s = (name or "").strip().lower()
    s = s.replace("microsoft/", "")
    for suf in (" mcp", "-mcp", "_mcp", " server", "-server", "_server"):
        s = s.replace(suf, " ")
    s = re.sub(
        r"[^a-z0-9]+", "", s
    )  # file system -> filesystem ; sequential-thinking -> sequentialthinking
    # 再剥尾巴的 mcp / server（如 "playwrightmcp" -> "playwright"）
    for tail in ("mcp", "server"):
        if s.endswith(tail) and len(s) > len(tail):
            s = s[: -len(tail)]
    s = re.sub(r"[^a-z0-9]+", "", s)
    return _TYPO_FIX.get(s, s)


def _build_alias_index() -> dict[str, str]:
    """归一化别名 → 规范名（CATALOG key）。把每条 entry 的 name + aliases 都登记进去。"""
    idx: dict[str, str] = {}
    for key, entry in CATALOG.items():
        forms = {entry.name, key, *entry.aliases}
        for f in forms:
            idx[_normalize(f)] = key
    return idx


_ALIAS_INDEX = _build_alias_index()


def lookup(name: str) -> McpEntry | None:
    """按名称查目录（走 alias 索引，容忍 OCR/字幕误记）。命中返回 McpEntry，未命中返回 None。"""
    key = _ALIAS_INDEX.get(_normalize(name))
    return CATALOG[key] if key else None


def usability_of(entry: McpEntry) -> str:
    """推导一条 MCP 的 usability（D22 反黑箱）。

    优先级：needs_credentials > needs_config > needs_runtime > ready。
    （目录里这几项互不重叠，优先级仅为防御性约定。）
    """
    if entry.credential_env:
        return "needs_credentials"
    if entry.needs_config:
        return "needs_config"
    if entry.needs_runtime:
        return "needs_runtime"
    return "ready"


# ---- 未收录项的人工候选提示（D19 先判 / D22 反黑箱） ----
# catalog miss 时，verify 把未命中项透传进 unresolved[]。对其中「字幕说法虽不精确，
# 但官方确有接近方案」的，这里给一条候选让用户拍板——绝不替用户臆造包装，只指路。
# key 为归一化名（同 _normalize），value = (候选包/仓, 说明)。
UNRESOLVED_HINTS: dict[str, tuple[str, str]] = {
    "memos": (
        "@modelcontextprotocol/server-memory",
        "字幕『memos』无官方 MCP 包；最接近的官方方案是 memory server"
        "（本地知识图谱式记忆），与字幕描述的『长期记忆』语义接近。"
        "是否采用需你拍板，不自动包装。",
    ),
}


def suggest_candidate(name: str) -> dict | None:
    """对 catalog miss 的名称，若有人工候选提示则返回 {candidate, reason}，否则 None。

    让 unresolved 项不仅报『未收录』，还给出可执行的下一步（D22 反黑箱：透明指路，
    把决策权交用户，而非黑箱吞掉或臆造包装）。
    """
    hint = UNRESOLVED_HINTS.get(_normalize(name))
    if not hint:
        return None
    candidate, reason = hint
    return {"candidate": candidate, "reason": reason}
