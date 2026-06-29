"""`install` 子命令：按去重结果安装能力到 Skill 目录并登记台账。"""

from __future__ import annotations

import argparse
import traceback

from skillbrew import llm, notify
from skillbrew.config import load_config

from ..utils import _resolve_source


def cmd_install(args: argparse.Namespace) -> int:
    """安装：照 dedup 判定的 new skill，整目录拷到运行时默认 Skill 目录，登记台账。"""
    from skillbrew import install as install_mod

    cfg = load_config()  # 校验配置 + 路径解析一致（install 不用 LLM，纯 GitHub raw）
    src = _resolve_source(cfg, args.source)
    if not (src / "install_list.json").exists():
        print(f"[ERR] {src} 没有 install_list.json（先跑 verify）")
        return 1
    if not (src / "dedup.json").exists():
        print(f"[ERR] {src} 没有 dedup.json（先跑 dedup）")
        return 1

    mode = "真装" if args.approve else "dry-run（只列计划，不下载不写台账）"
    print(f"[安装] {src}  {mode}")

    def on_progress(s: dict, i: int, n: int) -> None:
        form = s.get("form", "Skill")
        cat = s.get("category", "")
        head = f"{form}/{cat}" if cat else form
        if form == "MCP":
            mcp = s.get("mcp") or {}
            print(
                f"   [{i + 1}/{n}] 注册 MCP 服务器 {head}/{s['name']}"
                f"（{mcp.get('transport', 'stdio')} -s {mcp.get('scope', 'user')}）...",
                flush=True,
            )
        elif form == "repo":
            print(
                f"   [{i + 1}/{n}] clone {head}/{s['name']}"
                f"（{s.get('repo', '')}，分支 {s.get('branch', 'main')}）...",
                flush=True,
            )
        else:
            print(f"   [{i + 1}/{n}] 装 {head}/{s['name']}（整目录拷）...", flush=True)

    # D23：仅 --ai-infer 才注入 chat_fn（DeepSeek），让 install() 对 unresolved MCP 推断装法。
    # 默认关 → install() 纯查表，零行为改变（回归安全）。prompt_fn=None：交互终端走 input()，无终端写进报告。
    chat_fn = (lambda p: llm.chat_text(cfg, p)) if args.ai_infer else None

    try:
        r = install_mod.install(
            src,
            target_dir=args.target_dir,
            approve=args.approve,
            include_deprecated=args.include_deprecated,
            on_progress=on_progress,
            ai_infer=args.ai_infer,
            no_trial=args.no_trial,
            refresh_cache=args.refresh_cache,
            chat_fn=chat_fn,
            prompt_fn=None,
        )
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print(f"[FAIL] 安装失败：{e}")
        return 2

    print("\n" + "=" * 60)
    # per-item 形态明细（反黑箱 D22）：MCP 列 command/args/scope/usability，Skill 列目标+文件数
    detail = r.get("items_detail") or []
    first_form = detail[0].get("form", "Skill") if detail else "Skill"
    if first_form == "repo":
        repo_id = detail[0].get("repo", "") or "(未知)"
        print(f"源视频：{r['source_video']}  repo：{repo_id}")
    elif first_form == "MCP":
        print(f"源视频：{r['source_video']}  形态：MCP（{len(detail)} 个能力）")
    else:
        print(f"源视频：{r['source_video']}  仓库：{r['verified_repo'] or '(未知)'}")
    print(f"目标目录：{r['target_dir']}  安装前 distinct：{r['before']}")
    print(f"将装 new：{len(detail)} 个")
    for it in detail:
        form = it.get("form", "Skill")
        usab = it.get("usability", "ready")
        flag = f" [{usab}]" if usab and usab != "ready" else ""
        if form == "MCP":
            cmd = it.get("command", "")
            argstr = " ".join(it.get("args", []))
            print(
                f"  - {it['name']}（MCP，{it.get('transport', 'stdio')} -s {it.get('scope', 'user')}，"
                f"{cmd} {argstr}）{flag}"
            )
        elif form == "repo":
            print(
                f"  - {it['name']}（repo，clone → {it.get('repo', '')}，"
                f"分支 {it.get('branch', 'main')}）{flag}"
            )
        else:
            print(f"  - {it['name']}（Skill → {it.get('target', '')}）{flag}")
    if r["skipped_merge"]:
        print(f"跳过 merge（人工确认）：{len(r['skipped_merge'])} 个 → {r['skipped_merge']}")
    if r["skipped_deprecated"]:
        print(
            f"跳过 deprecated：{len(r['skipped_deprecated'])} 个 → {r['skipped_deprecated']}（--include-deprecated 可装）"
        )
    if r["skipped_already"]:
        print(f"跳过已装/已整并：{len(r['skipped_already'])} 个")
    unresolved = r.get("unresolved") or []
    if unresolved:
        print(f"unresolved（待你拍板，不自动包装）：{len(unresolved)} 个")
        for u in unresolved:
            print(f"  · {u.get('name')}：{u.get('reason')}（候选：{u.get('candidate', '')}）")
    resolve_traces = r.get("resolve_traces") or []
    if resolve_traces:
        print(f"\nAI 推断明细（resolve trace）：{len(resolve_traces)} 条")
        for t in resolve_traces:
            print(f"  · {t}")
    if args.approve:
        installed = r.get("installed", [])
        print(f"\n✅ 已落盘 {len(installed)} 个能力，安装后 distinct：{r.get('after')}")
        for s in installed:
            form = s.get("form", "Skill")
            if form == "MCP":
                usab = s.get("usability", "ready")
                flag = f" [{usab}]" if usab and usab != "ready" else ""
                print(
                    f"  - {s['name']}（MCP，{s.get('registered_via')}，scope={s.get('scope')}，"
                    f"{s.get('transport', 'stdio')}）→ {s.get('path', '')}{flag}"
                )
            elif form == "repo":
                usab = s.get("usability", "ready")
                flag = f" [{usab}]" if usab and usab != "ready" else ""
                cloned = "新克隆" if s.get("cloned_now") else "已存在(幂等跳过)"
                deps = (
                    "依赖✅"
                    if s.get("deps_installed")
                    else f"依赖待补({s.get('deps_method', 'none')})"
                )
                print(
                    f"  - {s['name']}（repo，{s.get('repo', '')}@{s.get('branch', 'main')}，"
                    f"{cloned}，{deps}）→ {s.get('path', '')}{flag}"
                )
            else:
                print(f"  - {s['name']}（{s.get('file_count', 0)} 文件）→ {s.get('path', '')}")
        if r.get("skipped_credentials"):
            names = ", ".join(d["name"] for d in r["skipped_credentials"])
            print(
                f"   跳过需凭证：{len(r['skipped_credentials'])} 个 → {names}（配 credential_env 后重跑）"
            )
        if r.get("skipped_config"):
            names = ", ".join(d["name"] for d in r["skipped_config"])
            print(f"   跳过需配置：{len(r['skipped_config'])} 个 → {names}（替换占位符后重跑）")
        print(f"   {r.get('note', '')}")
        # 邮件通知（可选）：install --approve 真装完成才发 HTML 报告（用户立规，
        # 延续 feedback-install-report-email）。未配置→主动提示一次（不报错）；
        # 配置→发完回执；发送本身失败也不影响安装结果。
        if notify.is_configured():
            res = notify.send_html(
                f"[skillbrew] 安装完成 · {r.get('source_video', '')}",
                notify.install_report_html(r, src),
            )
            if res.get("success"):
                print(f"   📧 已发完成报告邮件 → {res.get('to')}")
            else:
                reason = res.get("error") or res.get("reason") or "未知"
                print(f"   ⚠ 邮件未发出：{reason}")
        else:
            print(f"   💡 {notify.unconfigured_hint()}")
    else:
        print("\n   " + r.get("note", ""))
        print("   加 --approve 才真落盘 + 写台账。")
    print("=" * 60)
    return 0
