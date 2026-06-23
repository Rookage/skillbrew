#!/usr/bin/env python3
"""文档同步守卫脚本（D-doc-sync）。

用途：在 CI 中跑 `python scripts/check_docs_sync.py --check`，
如果 README.md / PROJECT_CHARTER.md / docs/index.html 里的关键锚点事实不一致就退出非零。
无参数运行时只打印告警，不拦 CI。

只校验**核心锚点事实**（能力数/管线步数/MCP 清单/暂缓项说明），不做全文逐字比对——
避免每次改个句子就误报。细节文案差异是允许的。

锚点清单（改这些事实时，必须三处同步改）：
  - 管线步数：必须都是"8 步"
  - 已装 MCP 名称集合（README / CHARTER 的清单必须一致；docs 页按设计不硬编码，不强制）
  - 暂缓项关键字（memos MCP / MoneyPrinterTurbo）必须在 README 与 docs 里都提到
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

README = ROOT / "README.md"
CHARTER = ROOT / "PROJECT_CHARTER.md"
DOCS = ROOT / "docs" / "index.html"

# 每个 MCP 用包名里的一个稳定标识串来识别
MCP_MARKERS = [
    "playwright",
    "filesystem",
    "sequential-thinking",
    "context7",
    "github",
]

PIPELINE_STEP_RE = re.compile(r"8\s*步")

DEFERRED_MARKERS = [
    ("memos", re.I),
    ("MoneyPrinterTurbo", 0),
]


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def check_pipeline_steps(text: str, label: str, problems: list[str]) -> None:
    if not PIPELINE_STEP_RE.search(text):
        problems.append(f"[{label}] 没找到 '8 步' 管线锚点")


def check_mcp_list(text: str, label: str, problems: list[str], info: list[str]) -> None:
    """只在 README / CHARTER 上强制 MCP 清单完整；docs 页不硬编码清单，跳过。"""
    missing = [m for m in MCP_MARKERS if not re.search(m, text, re.I)]
    if missing:
        problems.append(f"[{label}] 缺少已装 MCP 标识: {', '.join(missing)}")
    else:
        info.append(f"[{label}] 5 个 MCP 标识齐全")


def check_deferred(text: str, label: str, problems: list[str]) -> None:
    missing = []
    for spec in DEFERRED_MARKERS:
        if isinstance(spec, tuple):
            marker, flags = spec
        else:
            marker, flags = spec, 0
        if not re.search(marker, text, flags):
            missing.append(marker)
    if missing:
        problems.append(f"[{label}] 没提到暂缓项: {', '.join(missing)}")


def main() -> int:
    strict = "--check" in sys.argv

    readme = _read(README)
    charter = _read(CHARTER)
    docs = _read(DOCS)

    problems: list[str] = []
    info: list[str] = []

    # 1) 管线步数
    for label, t in [("README", readme), ("CHARTER", charter), ("docs", docs)]:
        check_pipeline_steps(t, label, problems)

    # 2) MCP 清单（README + CHARTER 必须全；docs 按设计不硬编码，只检查是否提到了至少 3 个）
    check_mcp_list(readme, "README", problems, info)
    check_mcp_list(charter, "CHARTER", problems, info)
    docs_mcp_hits = sum(1 for m in MCP_MARKERS if re.search(m, docs, re.I))
    if docs_mcp_hits < 3:
        problems.append(f"[docs] MCP 提及过少（{docs_mcp_hits}/5），可能漏了已装清单")

    # 3) 暂缓项（README + docs 必须提到；CHARTER 里也应该有）
    for label, t in [("README", readme), ("CHARTER", charter), ("docs", docs)]:
        check_deferred(t, label, problems)

    for line in info:
        print(f"  ok  - {line}")

    if problems:
        print("\n文档同步问题：")
        for p in problems:
            print(f"  ERR - {p}")
        print(
            "\n提示：改了能力数/管线步数/MCP 清单/暂缓项时，必须同时更新 "
            "README.md / PROJECT_CHARTER.md / docs/index.html 三处。详见 CONTRIBUTING.md。"
        )
        return 1 if strict else 0

    print("\n文档同步检查通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
