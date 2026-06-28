"""配置加载：分角色（D13 已拍板）。

两组完全独立：
  - 文本组 TEXT_*   → DeepSeek（消化 / 执行计划）
  - 视觉组 VISION_* → Agnes（关键帧看图）

.env 已 gitignore（D14 安全脱敏）。换供应商只改 .env，代码不动（D15 可插拔）。
真实环境变量优先于 .env 文件（方便 CI / 临时覆盖）。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def project_root() -> Path:
    """skillbrew/config.py → 包目录 → 项目根（.env 所在处）。"""
    return Path(__file__).resolve().parent.parent


def env_path() -> Path:
    return project_root() / ".env"


def load_env(path: Path | None = None, *, override: bool = False) -> None:
    """读取 .env 写入 os.environ。

    - 跳过空行与整行注释；
    - 剥离值里的行内 `#` 注释（仅当 # 前有空白才当注释，避免吞掉 URL 里的 #）；
    - 默认不覆盖已存在的环境变量（真实 env 优先），override=True 才覆盖。
    """
    path = path or env_path()
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = re.split(r"\s+#", val, maxsplit=1)[0]  # 剥行内注释
        val = val.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = val


@dataclass(frozen=True)
class ProviderConfig:
    base_url: str
    api_key: str
    model: str

    @property
    def is_complete(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    @property
    def missing(self) -> list[str]:
        return [
            name
            for name, v in (
                ("BASE_URL", self.base_url),
                ("API_KEY", self.api_key),
                ("MODEL", self.model),
            )
            if not v
        ]

    @property
    def key_masked(self) -> str:
        if len(self.api_key) <= 11:
            return "(未配置)" if not self.api_key else "***"
        return f"{self.api_key[:7]}...{self.api_key[-4:]}"


def _provider(prefix: str) -> ProviderConfig:
    """prefix 例: TEXT / VISION → 读 TEXT_BASE_URL / TEXT_API_KEY / TEXT_MODEL。"""
    return ProviderConfig(
        base_url=os.environ.get(f"{prefix}_BASE_URL", ""),
        api_key=os.environ.get(f"{prefix}_API_KEY", ""),
        model=os.environ.get(f"{prefix}_MODEL", ""),
    )


@dataclass(frozen=True)
class Config:
    text: ProviderConfig
    vision: ProviderConfig
    env_path: Path

    @property
    def root(self) -> Path:
        return project_root()

    @property
    def data_dir(self) -> Path:
        return self.root / "data"


def load_config(path: Path | None = None) -> Config:
    """加载 .env 并返回解析后的分角色配置。"""
    load_env(path)
    return Config(
        text=_provider("TEXT"),
        vision=_provider("VISION"),
        env_path=path or env_path(),
    )


# ---- 运行时探测（Claude Code / Codex / 其它 agent CLI）----

# 默认注册 scope：user（全项目可见、无需逐仓审批；local 仅当前目录，project 需入仓 .mcp.json 审批）
mcp_default_scope: str = "user"


def detect_runtime() -> str:
    """探测当前 agent 运行时，返回 'claude' | 'codex'。

    探测顺序：
      1. 环境变量 ``SKILLBREW_RUNTIME``（部署方显式指定，不进仓库）；
      2. Claude Code 特征：``CLAUDECODE=1`` 或 ``CLAUDE_CODE_SESSION_ID`` /
         ``CLAUDE_CODE_EXECPATH`` 任一存在 → 'claude'；
      3. Codex 特征：``CODEX_HOME`` 存在，或 ``~/.codex`` 目录存在 → 'codex'；
      4. 默认返回 'claude'。

    修正：本环境同时存在 ``~/.claude.json`` 与 ``~/.codex`` 目录，优先认
    Claude Code 专属环境变量，避免把 MCP 错写到 Codex 配置里。
    """
    env_hint = (os.environ.get("SKILLBREW_RUNTIME") or "").strip().lower()
    if env_hint in ("claude", "codex"):
        return env_hint
    if (
        os.environ.get("CLAUDECODE") == "1"
        or os.environ.get("CLAUDE_CODE_SESSION_ID")
        or os.environ.get("CLAUDE_CODE_EXECPATH")
    ):
        return "claude"
    if os.environ.get("CODEX_HOME"):
        return "codex"
    if (Path.home() / ".codex").exists():
        return "codex"
    return "claude"


# ---- Claude / Codex 配置根目录 ----


def claude_home() -> Path:
    """返回当前运行时的配置根目录（存放 INSTALLED_INDEX.md / CLAUDE.md / 等用户级文件）。

    优先级：
      1. 环境变量 ``SKILLBREW_CLAUDE_HOME``（部署方显式指定，不进仓库）；
      2. 运行时感知默认：
         - Claude Code → ``~/.claude``
         - Codex       → ``~/.codex``
    """
    env_hint = os.environ.get("SKILLBREW_CLAUDE_HOME")
    if env_hint:
        return Path(env_hint)
    if detect_runtime() == "codex":
        return Path.home() / ".codex"
    return Path.home() / ".claude"


# ---- MCP（模型上下文协议）安装相关配置 ----


def claude_json_path() -> Path:
    """返回当前运行时的 MCP 配置文件路径。

    优先级：
      1. 环境变量 ``SKILLBREW_CLAUDE_JSON``（部署方显式指定，不进仓库）；
      2. 运行时感知默认：
         - Claude Code → ``~/.claude.json``
         - Codex       → ``~/.codex/config.toml``

    注意：Codex 使用 TOML 格式，读写由 install._toml_* 工具函数完成（文本级段切分，
    不做全量 TOML 解析，用户其他 section/注释原样保留）。
    """
    env_hint = os.environ.get("SKILLBREW_CLAUDE_JSON")
    if env_hint:
        return Path(env_hint)
    if detect_runtime() == "codex":
        return Path.home() / ".codex" / "config.toml"
    return Path.home() / ".claude.json"


def skills_dir() -> Path:
    """返回 Skill 落地的用户级根目录。

    优先级：
      1. 环境变量 ``SKILLBREW_SKILLS_DIR``（部署方显式指定，不进仓库）；
      2. 运行时感知默认：
         - Claude Code → ``~/.claude/skills``
         - Codex       → ``~/.codex/skills``
    """
    env_hint = os.environ.get("SKILLBREW_SKILLS_DIR")
    if env_hint:
        return Path(env_hint)
    runtime = detect_runtime()
    if runtime == "codex":
        return Path.home() / ".codex" / "skills"
    return Path.home() / ".claude" / "skills"


def claude_bin() -> str | None:
    """返回可用的 claude 可执行文件路径，找不到返回 None。

    探测顺序（通用，不写死本机路径）：
      1. 环境变量 ``SKILLBREW_CLAUDE_BIN`` —— 部署方显式指定 bundled 二进制路径
         （如 Coze 3.0 随 SDK 打包的 claude v2.1.156，支持 ``claude mcp add -s
         user`` / ``get`` / ``list`` / ``remove`` 子命令；该 env 只存在本机、不进仓库）；
      2. PATH 上的 ``claude``（shutil.which）—— 通用环境优先走这条；
      3. Claude Code SDK 自带的 bundled binary：先读 ``CLAUDE_CODE_EXECPATH``，
         否则探测 ``~/.coze/bridge/lib/node_modules/@anthropic-ai/claude-agent-sdk-*/claude``；
      4. 都没有 → None，install 退回原子 JSON 合并 fallback。
    """
    env_hint = os.environ.get("SKILLBREW_CLAUDE_BIN")
    if env_hint and os.access(env_hint, os.X_OK):
        return env_hint
    found = shutil.which("claude")
    if found and os.environ.get("SKILLBREW_CLAUDE_BIN_OK", "1") != "0":
        # 若 claude 在 PATH 上但其实是 Coze SDK 里的代理壳子（``claude mcp get`` 会 hang），
        # 可通过 SKILLBREW_CLAUDE_BIN_OK=0 强制退回 JSON merge fallback。
        try:
            probe = subprocess.run(
                [found, "mcp", "list"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if probe.returncode == 0:
                return found
            # returncode 非 0 或超时 → 当成不可用，继续探测 fallback
        except (subprocess.TimeoutExpired, OSError):
            pass
    exec_env = os.environ.get("CLAUDE_CODE_EXECPATH")
    if exec_env and os.access(exec_env, os.X_OK):
        # 同样 probe 一下：若 claude mcp list 超时/非零返回，当成不可用，继续走 fallback
        try:
            probe = subprocess.run(
                [exec_env, "mcp", "list"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if probe.returncode == 0:
                return exec_env
        except (subprocess.TimeoutExpired, OSError):
            pass
    # 探测 Coze / Claude Code 打包路径（按当前平台取对应二进制）
    bridge = Path.home() / ".coze" / "bridge" / "lib" / "node_modules"
    import platform

    arch = platform.machine().lower()
    platform_tag = "linux-x64"
    if "arm64" in arch or "aarch64" in arch:
        platform_tag = "linux-arm64"
    bundled = bridge / "@anthropic-ai" / f"claude-agent-sdk-{platform_tag}" / "claude"
    if bundled.exists() and os.access(bundled, os.X_OK):
        try:
            probe = subprocess.run(
                [str(bundled), "mcp", "list"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if probe.returncode == 0:
                return str(bundled)
        except (subprocess.TimeoutExpired, OSError):
            pass
    # 兜底：通配列出所有 claude-agent-sdk-* 目录，对每个可执行文件 probe
    for candidate in sorted((bridge / "@anthropic-ai").glob("claude-agent-sdk-*/claude")):
        if os.access(candidate, os.X_OK):
            try:
                probe = subprocess.run(
                    [str(candidate), "mcp", "list"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if probe.returncode == 0:
                    return str(candidate)
            except (subprocess.TimeoutExpired, OSError):
                continue
    return None


# ---- repo（克隆即用）形态安装相关配置 ----


# 克隆即用仓库的落地根目录（镜像 ~/.claude/skills/ 的用户级约定：clone 下来的
# 开源项目统一放这里，便于去重扫描与卸载回滚）。可用环境变量 SKILLBREW_CLONES_DIR
# 覆盖（部署方显式指定，如指向更大的工作盘；该 env 只存在本机、不进仓库）。
def repo_clones_dir() -> Path:
    """返回克隆即用仓库的落地根目录。

    优先级：
      1. 环境变量 ``SKILLBREW_CLONES_DIR``（部署方显式指定，不进仓库）；
      2. 运行时感知默认：
         - Claude Code → ``~/.claude/clones``
         - Codex       → ``~/.codex/clones``
    """
    env_hint = os.environ.get("SKILLBREW_CLONES_DIR")
    if env_hint:
        return Path(env_hint)
    runtime = detect_runtime()
    if runtime == "codex":
        return Path.home() / ".codex" / "clones"
    return Path.home() / ".claude" / "clones"


# ---- D23 通用安装器：本地缓存 + 终端探测 ----


def install_cache_path() -> Path:
    """返回 D23 通用安装器的本地缓存文件 ``data/install_cache.json``。

    缓存「验证过的装法」（D23 四级降级链第 1 级：命中即用、不问 AI）。随 ``data/``
    自动 gitignore（仓库根 ``data/`` 已在 ``.gitignore``）。D14 卫生：缓存只存环境
    变量**名**、不存**值**（值恒空串），详见 ``installer.cache_store`` 的卫生器。

    与 ``data_dir`` 同源（项目根 ``data/``，非运行时相关），故不提供 env 覆盖——
    它是项目本地数据，不是运行时配置落点（区别于 ``skills_dir``/``claude_json_path``
    那类需随 Claude/Codex 运行时切换的路径）。
    """
    return project_root() / "data" / "install_cache.json"


def has_tty() -> bool:
    """当前进程是否挂在交互终端上（决定缺项补全走 ``input()`` 还是写报告）。

    headless 环境（如本 Coze 运行时 stdin 被重定向/管道）返回 False，``prompt_missing``
    降级为「把缺项清单写进报告、由 agent 在对话里转达用户」，**绝不卡死、绝不抛裸异常**。
    单独提函数（而非各处直接 ``sys.stdin.isatty()``）是为了测试里能 monkeypatch。
    """
    return bool(sys.stdin.isatty())


# ---- 终端编码兜底（Windows GBK 防 print 崩，issue #5）----


def ensure_utf8_stdout() -> None:
    """把 stdout/stderr 统一强制成 UTF-8 + errors=replace。

    Windows 默认控制台编码 GBK，print 含 ``\\u200b``（零宽空格，B站/抖音标题常见）等
    字符时直接 ``UnicodeEncodeError: 'gbk' codec can't encode ...`` 崩在最后一刻——
    明明下载成功却因打日志崩（issue #5）。统一 UTF-8 后所有 print 都不会因编码炸，
    编不出就 replace 成 ``?`` 而非抛异常。非 TextIOWrapper（如重定向到文件）或无
    ``reconfigure``（极老 Python）时静默跳过，不影响库式调用。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass
