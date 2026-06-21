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


# ---- MCP（模型上下文协议）安装相关配置 ----

# Claude Code 全局配置文件：mcpServers 注册落点
#   - user scope：顶层 mcpServers（全项目可见）
#   - local scope：projects[cwd].mcpServers（仅当前目录）
claude_json_path: Path = Path.home() / ".claude.json"

# 默认注册 scope：user（全项目可见、无需逐仓审批；local 仅当前目录，project 需入仓 .mcp.json 审批）
mcp_default_scope: str = "user"

def claude_bin() -> str | None:
    """返回可用的 claude 可执行文件路径，找不到返回 None。

    探测顺序（通用，不写死本机路径）：
      1. 环境变量 ``SKILLBREW_CLAUDE_BIN`` —— 部署方显式指定 bundled 二进制路径
         （如 Coze 3.0 随 SDK 打包的 claude v2.1.156，支持 ``claude mcp add -s
         user`` / ``get`` / ``list`` / ``remove`` 子命令；该 env 只存在本机、不进仓库）；
      2. PATH 上的 ``claude``（shutil.which）—— 通用环境优先走这条；
      3. 都没有 → None，install 退回原子 JSON 合并 fallback。
    """
    env_hint = os.environ.get("SKILLBREW_CLAUDE_BIN")
    if env_hint and os.access(env_hint, os.X_OK):
        return env_hint
    found = shutil.which("claude")
    if found:
        return found
    return None
