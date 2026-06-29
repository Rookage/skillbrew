"""`add` 子命令：把一个 MCP（模型上下文协议）服务器注册进配置 + 登记台账（issue #27 Phase 2）。

薄壳：解析 CLI 参数 → 调 install.register_mcp（通用注册原语）→ 把结果排成可读文本。
register_mcp 内部复用 install 的原子写入器 + registry 台账，本命令不重复造轮子。

三种入口（都落到同一个 register_mcp 原语，不绑死任何市场）：
- 远程 HTTP：`add NAME --url URL [-H K:V]`（主场景：Smithery 多为远程托管）
- 本地 stdio：`add NAME --command CMD [--arg A ...] [--env KEY]`
- 从市场拉：`add NAME --from smithery`（自动取远程 URL；本地 stdio 详情不含装法，提示手动）

默认 dry-run（反盲盒 D22），--approve 才真写。env/headers 在预览里脱敏（D14）。
"""

from __future__ import annotations

import argparse

from skillbrew import install as install_mod
from skillbrew import marketplace


def _parse_header(raw: str) -> tuple[str, str]:
    """把 ``Key: Value`` 拆成 (key, value)；缺冒号报错。"""
    if ":" not in raw:
        raise ValueError(f"header 格式应为 'Key: Value'，收到：{raw}")
    k, v = raw.split(":", 1)
    return k.strip(), v.strip()


def cmd_add(args: argparse.Namespace) -> int:
    """`skillbrew add ...` —— 注册一个 MCP 服务器。"""
    name = (args.name or "").strip()
    if not name:
        print("[FAIL] add 需要一个 MCP 名（如 `skillbrew add github --url ...`）")
        return 2

    transport = (args.transport or "").strip().lower() or None
    url = args.url
    command = args.command
    argv = list(args.arg or [])
    env_keys = list(args.env or [])
    scope = (args.scope or "user").strip().lower()
    source = ""
    homepage_hint = ""

    # ---- 1. 从市场拉：解析远程 URL（远程托管可直接装；本地 stdio 提示手动）----
    if args.from_smithery:
        try:
            detail = marketplace.info(name)
        except marketplace.MarketplaceError as err:
            print(f"[FAIL] 从市场拉详情失败：{err}")
            return 2
        name = detail.qualified_name or name
        source = f"smithery:{detail.qualified_name}"
        homepage_hint = detail.homepage
        if detail.remote and detail.deployment_url:
            transport = transport or "http"
            url = detail.deployment_url
            if detail.needs_config:
                print(f"提示：{detail.display_name} 需配置参数，可用 --env KEY 声明。")
        else:
            # 本地 stdio：Smithery 详情不含 command/args，没法自动装
            print(f"{detail.display_name}（{detail.qualified_name}）是本地 stdio 服务器。")
            print("市场详情不含安装命令，需手动指定装法，例如：")
            print(
                f"  skillbrew add {detail.qualified_name} --command npx "
                f"--arg -y --arg <npm包名> [--env <KEY>]"
            )
            if detail.needs_config and detail.homepage:
                print(f"该服务器还需配置参数，详见：{detail.homepage}")
            return 0

    # ---- 2. 手动模式：按 --url / --command 推断 transport ----
    elif url:
        transport = transport or "http"
    elif command:
        transport = transport or "stdio"
    else:
        print("[FAIL] 不知道怎么注册。给 --url（远程）、--command（本地）或 --from smithery（市场）。")
        print("  远程：skillbrew add NAME --url https://... [-H 'X-Token: abc']")
        print("  本地：skillbrew add NAME --command npx --arg=-y --arg <包名> [--env KEY]")
        print("  市场：skillbrew add NAME --from smithery")
        return 2

    # ---- 3. headers（仅 http/sse 有意义）----
    headers: dict[str, str] | None = None
    if args.header:
        headers = {}
        for raw in args.header:
            try:
                k, v = _parse_header(raw)
            except ValueError as err:
                print(f"[FAIL] {err}")
                return 2
            headers[k] = v

    # ---- 4. 调通用注册原语 ----
    try:
        result = install_mod.register_mcp(
            name,
            transport=transport or "stdio",
            url=url,
            command=command,
            args=argv,
            env_keys=env_keys,
            headers=headers,
            scope=scope,
            source=source,
            approve=args.approve,
        )
    except RuntimeError as err:
        print(f"[FAIL] {err}")
        return 2

    # ---- 5. 格式化输出（反盲盒 D22：说明装了什么、怎么用；D14：env/headers 脱敏）----
    tport = result["transport"]
    sc = result["scope"]
    server = result.get("server") or {}
    missing = result.get("missing_env") or []

    print(f"MCP「{result['name']}」　连接方式={tport}　scope={sc}")
    if result.get("approve"):
        via = result.get("registered_via", "-")
        src_tag = f"（source={source}）" if source else "（manual add）"
        print(f"[OK] 已写入：{result['path']}")
        print(f"     注册方式：{via}　台账已登记{src_tag}")
    else:
        print(f"[计划] 将写入：{result['path']}")
    print("  server 预览（env/headers 已脱敏）：")
    for k, v in server.items():
        print(f"    {k}: {v}")

    if missing:
        if result.get("approve"):
            tag = "（已注册但运行时可能起不来，export 后重启生效）"
        else:
            tag = "（用 --env 声明 + export 后 --approve）"
        print(f"  [缺环境变量] {', '.join(missing)} {tag}")
        if homepage_hint:
            print(f"  配置说明见：{homepage_hint}")

    print()
    if result.get("approve"):
        print("怎么用：重启 Claude Code 后该 MCP 自动加载，其工具直接可调用。")
    else:
        print("dry-run：未写配置、未登台账。加 --approve 才真装。")
    return 0
