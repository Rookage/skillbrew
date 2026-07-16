"""CLI argparse 装配与全局标志透传。"""

from __future__ import annotations

import argparse
import os

from skillbrew import __version__

from .commands import (
    cmd_add,
    cmd_config,
    cmd_dedup,
    cmd_doctor,
    cmd_info,
    cmd_ingest,
    cmd_install,
    cmd_plan,
    cmd_recommend,
    cmd_record,
    cmd_run,
    cmd_search,
    cmd_understand,
    cmd_verify,
)


def build_parser() -> argparse.ArgumentParser:
    """装配 skillbrew 子命令解析器。"""
    parser = argparse.ArgumentParser(
        prog="skillbrew",
        description="AI 能力包管理器：素材 → 消化 → 计划 → 授权安装 → 能力台账",
    )
    parser.add_argument("--version", action="version", version=f"skillbrew {__version__}")
    parser.add_argument(
        "--runtime",
        choices=["claude", "codex"],
        default=None,
        help="显式指定 agent 运行时（默认自动探测：CODEX_HOME 或 ~/.codex 存在则 codex，否则 claude）",
    )
    parser.add_argument(
        "--clones-dir",
        default=None,
        metavar="DIR",
        help="覆盖默认 clone 落地目录（env SKILLBREW_CLONES_DIR 优先级更高）",
    )
    parser.add_argument(
        "--mcp-json",
        default=None,
        metavar="PATH",
        help="覆盖默认 MCP 配置文件路径（env SKILLBREW_CLAUDE_JSON 优先级更高）",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_doc = sub.add_parser("doctor", help="自检：配置 + 文本/视觉连通性")
    p_doc.add_argument(
        "--vision", action="store_true", help="额外跑一次真·看图实测（Agnes ~5min/张）"
    )
    p_doc.set_defaults(func=cmd_doctor)

    p_cfg = sub.add_parser("config", help="打印解析后的配置（key 脱敏）")
    p_cfg.set_defaults(func=cmd_config)

    p_run = sub.add_parser("run", help="一键：采集→理解→消化→草稿计划（到此为止，不安装）")
    p_run.add_argument("source", help="B站 URL 或 BV 号")
    p_run.add_argument("--qn", type=int, default=32, help="清晰度 16/32/64/80")
    p_run.add_argument("--max-frames", type=int, default=5, help="关键帧数")
    p_run.add_argument("--max-workers", type=int, default=3, help="视觉并发数")
    p_run.add_argument("--skip-asr", action="store_true", help="跳过字幕转写")
    p_run.add_argument(
        "--skip-vision", action="store_true", help="跳过视觉看图（省时，纯字幕消化）"
    )
    p_run.add_argument("--force", action="store_true", help="不跳过已有产物，重跑")
    p_run.set_defaults(func=cmd_run)

    p_ing = sub.add_parser("ingest", help="只跑采集（下载视频 + 音频）")
    p_ing.add_argument("source", help="B站 URL 或 BV 号")
    p_ing.add_argument("--qn", type=int, default=32)
    p_ing.set_defaults(func=cmd_ingest)

    p_und = sub.add_parser("understand", help="只跑理解（字幕 + 关键帧 + 视觉）")
    p_und.add_argument("source", help="源目录 或 B站URL/BV号")
    p_und.add_argument("--max-frames", type=int, default=5)
    p_und.add_argument("--max-workers", type=int, default=3)
    p_und.add_argument("--skip-asr", action="store_true")
    p_und.add_argument("--skip-vision", action="store_true")
    p_und.add_argument("--force", action="store_true")
    p_und.set_defaults(func=cmd_understand)

    p_plan = sub.add_parser("plan", help="只跑消化（字幕 + 视觉 → 草稿计划）")
    p_plan.add_argument("source", help="源目录 或 B站URL/BV号")
    p_plan.set_defaults(func=cmd_plan)

    p_ver = sub.add_parser(
        "verify", help="溯源：回 GitHub 取一手资料，纠正草稿计划 + 出机器安装清单"
    )
    p_ver.add_argument("source", help="源目录 或 B站URL/BV号")
    p_ver.add_argument("--repo", default=None, help="手动指定 owner/repo（绕过自动搜索）")
    p_ver.set_defaults(func=cmd_verify)

    p_ded = sub.add_parser(
        "dedup", help="去重：扫本地已装 skill 建基准，比 install_list，判 new/merge/skip"
    )
    p_ded.add_argument("source", help="源目录 或 B站URL/BV号")
    p_ded.add_argument(
        "--skills-dir",
        action="append",
        default=None,
        metavar="DIR",
        help="追加要扫描的 Skill 目录（可重复；默认已含运行时默认 Skill 目录）",
    )
    p_ded.set_defaults(func=cmd_dedup)

    p_rec_judge = sub.add_parser(
        "recommend",
        help="判断步：去重后判「值不值得装」，出 recommend.json（不安装；keyword/manual 不烧 token）",
    )
    p_rec_judge.add_argument("source", help="源目录 或 B站URL/BV号")
    p_rec_judge.add_argument(
        "--skills-dir",
        action="append",
        default=None,
        metavar="DIR",
        help="追加扫描目录（默认已含运行时默认 Skill 目录，与去重同口径）",
    )
    p_rec_judge.add_argument(
        "--mode",
        choices=["keyword", "manual", "ai"],
        default="keyword",
        help="判断模式：keyword=规则打分(默认,无 key) / manual=人工勾选(无 key) / ai=文本模型(烧 token,需在场)",
    )
    p_rec_judge.add_argument(
        "--source-skip",
        default=None,
        metavar="REASON",
        help="整源跳过：手判该源非技能集（如配置商店）否决整源，approved 置空（D19 人定）",
    )
    p_rec_judge.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="ai 模式成本控制：只判前 N 条 new 候选（未判到的由 merge 兜底「不值得装」）",
    )
    p_rec_judge.set_defaults(func=cmd_recommend)

    p_inst = sub.add_parser(
        "install",
        help="安装：照 dedup 判定的 new skill，整目录拷到运行时默认 Skill 目录并登记台账",
    )
    p_inst.add_argument("source", help="源目录 或 B站URL/BV号")
    p_inst.add_argument(
        "--approve", action="store_true", help="真落盘 + 写台账（默认 dry-run，只列计划）"
    )
    p_inst.add_argument(
        "--include-deprecated",
        action="store_true",
        help="连 deprecated skill 一起装（默认跳过）",
    )
    p_inst.add_argument(
        "--target-dir", default=None, help="安装目标目录（默认运行时默认 Skill 目录）"
    )
    p_inst.add_argument(
        "--ai-infer",
        action="store_true",
        help="对 verify 标 unresolved 的 MCP，开 AI 读源头仓库推断装法+试跑验证+缺项补全（D23，默认关）",
    )
    p_inst.add_argument(
        "--no-trial",
        action="store_true",
        help="跳过装前试跑（推断后不验证直接装，未验证不入缓存）",
    )
    p_inst.add_argument(
        "--refresh-cache",
        action="store_true",
        help="忽略本地缓存重新推断装法（强刷已缓存的装法）",
    )
    p_inst.set_defaults(func=cmd_install)

    p_rec = sub.add_parser(
        "record",
        help="记录+看板：从台账/清单/去重一手数据代码生成安装记录与看板（只读，不改台账）",
    )
    p_rec.add_argument("source", help="源目录 或 B站URL/BV号")
    p_rec.add_argument(
        "--skills-dir",
        action="append",
        default=None,
        metavar="DIR",
        help="追加扫描目录（默认读 dedup.json 的 baseline.skill_dirs，与去重同口径）",
    )
    p_rec.set_defaults(func=cmd_record)

    p_search = sub.add_parser("search", help="在 MCP 市场搜 MCP 服务器（只读，不安装）")
    p_search.add_argument("query", help="搜索关键词")
    p_search.add_argument("--limit", type=int, default=10, metavar="N", help="每页条数（默认 10）")
    p_search.add_argument("--page", type=int, default=1, metavar="N", help="页码（默认第 1 页）")
    p_search.add_argument(
        "--market",
        choices=["smithery", "registry"],
        default=None,
        help="市场（默认 smithery；registry=官方 MCP Registry）",
    )
    p_search.set_defaults(func=cmd_search)

    p_info = sub.add_parser("info", help="看某个 MCP 在市场里的详情（只读，不安装）")
    p_info.add_argument("name", help="MCP 的 qualifiedName（如 github / ac.inference.sh/mcp）")
    p_info.add_argument(
        "--market",
        choices=["smithery", "registry"],
        default=None,
        help="市场（默认 smithery；registry=官方 MCP Registry）",
    )
    p_info.set_defaults(func=cmd_info)

    p_add = sub.add_parser(
        "add",
        help="注册一个 MCP 服务器进配置 + 登记台账（默认 dry-run，--approve 才真写）",
    )
    p_add.add_argument("name", help="MCP 名（注册 key）；--from 时用市场 qualifiedName")
    p_add.add_argument(
        "--from",
        dest="from_market",
        metavar="MARKET",
        choices=["smithery", "registry"],
        help="从市场拉详情自动取远程 URL（支持 smithery / registry）",
    )
    p_add.add_argument("--url", metavar="URL", help="远程 HTTP/SSE 地址（远程 MCP 用）")
    p_add.add_argument(
        "--transport",
        choices=["http", "sse", "stdio"],
        default=None,
        help="连接方式（默认按 --url/--command 推断；显式指定可强制 sse 等）",
    )
    p_add.add_argument("--command", metavar="CMD", help="本地 stdio 命令（如 npx）")
    p_add.add_argument(
        "--arg",
        action="append",
        default=None,
        metavar="ARG",
        help="本地命令的参数，可重复；值以 - 开头时用等号 --arg=-y（argparse 把 -y 当选项，"
        "如 --arg=-y --arg <包名>）",
    )
    p_add.add_argument(
        "-H",
        "--header",
        action="append",
        default=None,
        metavar="K:V",
        help="HTTP 头（可重复），如 -H 'X-Token: abc'",
    )
    p_add.add_argument(
        "--env",
        action="append",
        default=None,
        metavar="KEY",
        help="声明的环境变量名（可重复），值从 os.environ 取（stdio 凭证）",
    )
    p_add.add_argument(
        "--scope",
        choices=["user", "local", "project"],
        default="user",
        help="注册范围（默认 user 全局）",
    )
    p_add.add_argument(
        "--approve", action="store_true", help="真落盘 + 写台账（默认 dry-run，只预览）"
    )
    p_add.set_defaults(func=cmd_add)

    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析参数并把 CLI 全局标志透传为环境变量，确保运行时探测即时生效。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    # CLI 全局标志透传为环境变量，确保 config.detect_runtime()/skills_dir()/claude_json_path()
    # /repo_clones_dir() 在本进程内即时生效（env 优先级高于运行时默认）。
    if args.runtime:
        os.environ.setdefault("SKILLBREW_RUNTIME", args.runtime)
    if args.clones_dir:
        os.environ.setdefault("SKILLBREW_CLONES_DIR", args.clones_dir)
    if args.mcp_json:
        os.environ.setdefault("SKILLBREW_CLAUDE_JSON", args.mcp_json)

    return args
