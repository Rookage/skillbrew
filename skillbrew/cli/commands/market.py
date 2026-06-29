"""`search` / `info` 子命令：在 MCP 市场搜、看详情（issue #27 Phase 1，只读不装）。

薄壳：把参数转给 marketplace 层，把结果排成可读文本打到 stdout。不安装、不写配置。
"""

from __future__ import annotations

import argparse

from skillbrew import marketplace


def cmd_search(args: argparse.Namespace) -> int:
    """`skillbrew search <关键词>` —— 在 Smithery 搜 MCP。"""
    try:
        entries = marketplace.search(args.query, limit=args.limit, page=args.page)
    except marketplace.MarketplaceError as err:
        print(f"[FAIL] 搜索失败：{err}")
        return 2
    if not entries:
        print(f"没搜到匹配「{args.query}」的 MCP，换个关键词试试。")
        return 0
    print(f"在 Smithery 搜「{args.query}」，返回 {len(entries)} 条（第 {args.page} 页）：")
    print()
    for i, entry in enumerate(entries, 1):
        v = "✓" if entry.verified else " "
        kind = "远程" if entry.remote else "本地"
        print(f"{i:2}. [{v}] {entry.display_name}  ({entry.qualified_name})  [{kind}]  用 {entry.use_count}")
        desc = entry.description.replace("\n", " ")
        if len(desc) > 90:
            desc = desc[:87] + "..."
        print(f"    {desc}")
        if entry.homepage:
            print(f"    {entry.homepage}")
        print()
    print("提示：用 `skillbrew info <qualifiedName>` 看详情。")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    """`skillbrew info <qualifiedName>` —— 看某个 MCP 在市场里的详情。"""
    try:
        d = marketplace.info(args.name)
    except marketplace.MarketplaceError as err:
        print(f"[FAIL] 查详情失败：{err}")
        return 2
    print(f"{d.display_name}  ({d.qualified_name})")
    print("=" * 60)
    print(d.description)
    print()
    kind = "远程托管" if d.remote else "本地"
    print(f"连接方式：{d.transport or '未知'}（{kind}）")
    if d.deployment_url:
        print(f"部署地址：{d.deployment_url}")
    print(f"工具数：{d.tool_count}　提示词：{d.prompt_count}　资源：{d.resource_count}")
    print(f"需配置：{'是（需填参数）' if d.needs_config else '否'}")
    if d.homepage:
        print(f"主页：{d.homepage}")
    print()
    print("提示：安装命令 `skillbrew add` 尚未实现（Phase 2）。")
    return 0
