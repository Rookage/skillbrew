"""record：记录 + 看板 —— 从台账/清单/去重一手数据，代码生成安装记录与可视化看板。

Step 5（章程 D18 第五步）：把手工写的 POST_INSTALL.md / REPORT.md 变成代码生成。
所有数字来自实时查台账（registry.db）+ 扫磁盘（.claude/skills/）+ 读 install_list.json
/ dedup.json，不手写、不猜（刻舟求剑 §5.3：写死的计数一落笔就过时，故全部现取现算）。
纯标准库（sqlite3/json/pathlib + Markdown/Mermaid 文本），不调 LLM、不耗配额、不要 key。

产物两份写到源目录（不覆盖手工的 POST_INSTALL.md / REPORT.md，留作"代码 vs 手工"对照）：
  RECORD.md    本次安装台账记录：落地清单 / 台账 / 去重 / 落盘核对 / 回滚 / MIT 合规 / 调用方式（D22）
  DASHBOARD.md 本次 + 累计看板：顺藤摸瓜图 / 决策分布 / 两次会话累加 / 落盘完整性 / 调用方式（D22）

"你落盘就是什么"（章程 §4 台账定义）：看板含一道完整性核对——实时扫磁盘 active distinct
对台账 active，两者须相等；不等就如实列孤儿（磁盘有台账无）/缺失（台账有磁盘无），不粉饰。

诚实报告（不报喜不报忧）：本次代码 install 装的 skill 里，有 in-progress（未完成）/
personal（作者个人）类——代码去重只判"是否重复"（名字/描述重叠），不判"是否值得装"，
手动判断曾把这类标"跳过·不装"。record 如实标出，建议人工复核或后续给 install 加
`--exclude-categories`，不替用户遮掩。
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from . import config, registry
from . import dedup as dedup_mod  # 复用 scan_local_skills / _key 做落盘核对


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _short(s: str, n: int = 36) -> str:
    """描述压成一行短句，给表格"一句话"列用。"""
    s = (s or "").strip().replace("\n", " ").replace("|", "/")
    return s if len(s) <= n else s[: n - 1] + "…"


def _star_tag(repo: dict) -> str:
    """⭐星数〔取数时点〕—— 星数动态非定值（章程 5.3），必标时点。"""
    stars = repo.get("stars")
    ts = repo.get("stars_observed_at", "")
    if stars is None:
        return "（星数未取）"
    return f"⭐{stars}〔{ts} 取数〕"


def _source_label(name: str) -> str:
    """源素材平台标签：从源目录名推断（BV→B站、douyin→抖音），拿不准回退原名。
    能力包管理器的源不止 B 站——别把平台写死（D2 产物形态/源皆不预设）。"""
    n = (name or "").lower()
    if n.startswith("bv"):
        return "B站"
    if "douyin" in n:
        return "抖音"
    if "youtube" in n or n.startswith("yt"):
        return "YouTube"
    return name


# ---- 数据汇集：读全数据源，返回一个 dict 供两个生成器共用 ----

def _gather(source_dir: Path, skill_dirs: list[Path], db_path) -> dict:
    source_dir = Path(source_dir)
    il = json.loads((source_dir / "install_list.json").read_text(encoding="utf-8"))
    dd = json.loads((source_dir / "dedup.json").read_text(encoding="utf-8"))
    # 判断步（recommend）：可选——跑了 recommend 才有，没跑则 None，看板优雅降级（D19/D22）
    rec_path = source_dir / "recommend.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8")) if rec_path.exists() else None

    # D23: resolve-pass 的 provenance/trace/missing（install.py 写入的 sidecar）
    rt_path = source_dir / "resolve_trace.json"
    resolve_trace = json.loads(rt_path.read_text(encoding="utf-8")) if rt_path.exists() else None

    repo = il.get("verified_repo", {})

    # plan.json 一手留痕：OCR 纠错叙事、溯源说明、corrections（替代硬编码仓库名/星数）
    plan_path = source_dir / "plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8")) if plan_path.exists() else {}
    verify_blk = plan.get("_verify", {}) or {}
    traced = (plan.get("traced_sources") or [{}])[0]
    ocr_note = traced.get("note") or verify_blk.get("note") or ""
    verify_how = verify_blk.get("how_resolved") or repo.get("how_resolved", "")
    verify_corrections = verify_blk.get("corrections") or []
    items = il.get("items") or il.get("skills") or []  # items 规范键，skills 兼容别名（同数组引用）
    by_name = {s["name"]: s for s in items}

    # 台账（一手）
    conn = registry.connect(db_path if db_path is not None else registry.DB_PATH)
    try:
        all_skills = [dict(r) for r in registry.list_skills(conn)]  # 全状态
        sessions = [dict(r) for r in conn.execute(
            "SELECT * FROM install_sessions ORDER BY id")]
    finally:
        conn.close()
    active = [r for r in all_skills if r.get("status") == "active"]
    merged = [r for r in all_skills if r.get("status") == "merged"]
    reg_active_by_name = {r["name"]: r for r in active}

    # 落盘核对（形态感知，registry 作单一真相源）：Skill 扫磁盘目录 vs 台账 active(Skill)；
    # MCP 读 ~/.claude.json 注册表 vs 台账 active(MCP)；repo 扫 ~/.claude/clones/ vs 台账 active(repo)。
    # 三形态各自对齐，MCP/repo 项才进得了核对（D2/D22）。
    disk_entries = dedup_mod.scan_local_skills(skill_dirs)
    disk_skill_by_key = {dedup_mod._key(e["name"]): e for e in disk_entries}
    disk_mcps = dedup_mod.scan_local_mcps()
    disk_mcp_names = {m["name"] for m in disk_mcps}
    disk_repos = dedup_mod.scan_local_repos()  # [{name, repo, path, source}]
    disk_repo_fulls = {r["repo"].lower() for r in disk_repos if r.get("repo")}
    reg_active_skill = [r for r in active if (r.get("form") or "Skill") == "Skill"]
    reg_active_mcp = [r for r in active if (r.get("form") or "Skill") == "MCP"]
    reg_active_repo = [r for r in active if (r.get("form") or "Skill") == "repo"]
    reg_skill_by_key = {dedup_mod._key(r["name"]): r for r in reg_active_skill}
    reg_mcp_names = {r["name"] for r in reg_active_mcp}
    # repo 形态对齐键：台账行 source=仓全名（owner/repo），磁盘行 repo=同；归一化小写比对
    reg_repo_fulls = {(r.get("source") or r["name"]).lower() for r in reg_active_repo}
    orphan_skills = sorted(disk_skill_by_key[k]["name"] for k in disk_skill_by_key.keys() - reg_skill_by_key.keys())
    missing_skills = sorted(reg_skill_by_key[k]["name"] for k in reg_skill_by_key.keys() - disk_skill_by_key.keys())
    orphan_mcps = sorted(disk_mcp_names - reg_mcp_names)
    missing_mcps = sorted(reg_mcp_names - disk_mcp_names)
    orphan_repos = sorted(disk_repo_fulls - reg_repo_fulls)
    missing_repos = sorted(reg_repo_fulls - disk_repo_fulls)
    orphans = orphan_skills + orphan_mcps + orphan_repos
    missing = missing_skills + missing_mcps + missing_repos
    disk_distinct = len(disk_skill_by_key) + len(disk_mcp_names) + len(disk_repo_fulls)

    # repo 形态的身份来自首个 item（install_list 无 verified_repo 键，full_name 为空；
    # 故 §1/§7/看板取 repo_item 而非 g["full_name"]，避免误走 MCP 分支或假报 MIT 许可证）
    src_form = il.get("form") or "Skill"
    repo_item = items[0] if (src_form == "repo" and items) else {}

    # dedup 决策细拆（new 再拆 deprecated / 非deprecated）
    decs = dd.get("decisions", [])
    new_installed = [d for d in decs if d["decision"] == "new" and d.get("category") != "deprecated"]
    new_deprecated = [d for d in decs if d["decision"] == "new" and d.get("category") == "deprecated"]
    merge_cands = [d for d in decs if d["decision"] == "merge"]
    skips = [d for d in decs if d["decision"] == "skip"]

    # 本源的安装会话（一个源可能装多次，累加看全部）
    src_name = source_dir.name
    src_sessions = [s for s in sessions if s.get("source_video") == src_name]

    return {
        "source_dir": source_dir, "il": il, "dd": dd, "repo": repo,
        "full_name": repo.get("full_name", ""), "html_url": repo.get("html_url", ""),
        "how_resolved": repo.get("how_resolved", ""), "star_tag": _star_tag(repo),
        "total": il.get("total", len(items)), "by_name": by_name,
        "all_skills": all_skills, "active": active, "merged": merged,
        "reg_active_by_name": reg_active_by_name,
        "reg_active_skill": reg_active_skill, "reg_active_mcp": reg_active_mcp,
        "reg_active_repo": reg_active_repo,
        "sessions": sessions, "src_sessions": src_sessions,
        "disk_entries": disk_entries, "disk_distinct": disk_distinct,
        "disk_skill_distinct": len(disk_skill_by_key), "disk_mcp_count": len(disk_mcp_names),
        "disk_repo_count": len(disk_repo_fulls),
        "orphan_skills": orphan_skills, "missing_skills": missing_skills,
        "orphan_mcps": orphan_mcps, "missing_mcps": missing_mcps,
        "orphan_repos": orphan_repos, "missing_repos": missing_repos,
        "orphans": orphans, "missing": missing,
        "src_form": src_form, "repo_item": repo_item,
        "new_installed": new_installed, "new_deprecated": new_deprecated,
        "merge_cands": merge_cands, "skips": skips,
        "summary": dd.get("summary", {}), "skill_dirs": skill_dirs,
        "plan": plan, "ocr_note": ocr_note,
        "verify_how": verify_how, "verify_corrections": verify_corrections,
        "recommend": rec, "resolve_trace": resolve_trace,
    }


def _by_field(rows: list[dict], field: str, empty_label: str = "(未标)") -> dict:
    out: dict[str, int] = {}
    for r in rows:
        k = r.get(field) or empty_label
        out[k] = out.get(k, 0) + 1
    return out


def _session_label(i: int, choice: str) -> str:
    """把安装会话编号 + 授权选择转成图示标签：①手动 A / ②代码 --approve …"""
    circ = "①②③④⑤⑥⑦⑧⑨⑩"[i] if 0 <= i < 10 else f"#{i + 1}"
    c = choice or ""
    if c == "A":
        return f"{circ}手动 A"
    if c == "install --approve":
        return f"{circ}代码 --approve"
    return f"{circ}{c}"


def _session_arrows(sessions: list[dict]) -> str:
    """一行文字版累加轨迹：起步 → 每次（标注）→ … 全从 sessions 现取。"""
    if not sessions:
        return "（本源尚无安装会话）"
    parts = [str(sessions[0].get("skills_before", "?"))]
    for i, s in enumerate(sessions):
        parts.append(
            f"{s.get('skills_after', '?')}（{_session_label(i, s.get('authorization_choice', ''))}）"
        )
    return " → ".join(parts)


def _cumulative_flow(sessions: list[dict], active: list[dict], merged: list[dict]) -> list[str]:
    """before/after 累加 Mermaid 图：before/added/merged/after 全从 sessions 现取，
    不写死 25→40→54（刻舟求剑 §5.3）。最后一个会话节点同时承载当前台账。
    返回 Mermaid 行（不含 ```fence）。"""
    L = ["flowchart LR"]
    if not sessions:
        L.append('    E["（本源尚无安装会话）"]')
        return L
    b0 = sessions[0].get("skills_before", "?")
    L.append(f'    S0["起步<br/>{b0} distinct"]')
    prev = "S0"
    n = len(sessions)
    for i, s in enumerate(sessions):
        added = s.get("skills_added", 0)
        sm = s.get("skills_merged", 0)
        after = s.get("skills_after", "?")
        label = _session_label(i, s.get("authorization_choice", ""))
        edge = f'"+{added} 新' + (f" +{sm} 整并" if sm else "") + '"'
        if i == n - 1:  # 末个会话节点 = 台账，附 active+merged 细分
            detail = f"{len(active)} active+{len(merged)} merged" if merged else f"{len(active)} active"
            L.append(f'    {prev} -->|{edge}| S{i + 1}["{label}<br/>{after} distinct<br/>({detail})"]')
        else:
            L.append(f'    {prev} -->|{edge}| S{i + 1}["{label}<br/>{after}"]')
        prev = f"S{i + 1}"
    L.append("    classDef s fill:#e8f0fd,stroke:#2c6cb0;")
    L.append("    classDef e fill:#e8f8e8,stroke:#27ae60;")
    inner = ",".join(f"S{i}" for i in range(n))  # S0..S{n-1} = 起步+中间会话
    L.append(f"    class {inner} s;")
    L.append(f"    class S{n} e;")
    return L


def _trigger(desc: str) -> str:
    """从 description 抠触发提示词——D22「以后怎么调用」的核心：有 'Use when…' 从那里起取
    （这就是该技能的唤起条件），否则取首句兜底。压一行、限长，给表格列用。"""
    s = (desc or "").strip().replace("\n", " ").replace("|", "/")
    idx = s.lower().find("use when")
    if idx >= 0:
        s = s[idx:].strip()
    elif "。" in s:
        s = s.split("。", 1)[0].strip()
    elif ". " in s:
        s = s.split(". ", 1)[0].strip()
    return s if len(s) <= 110 else s[:109] + "…"


def _invoke_hint(name: str, form: str | None) -> str:
    """每个能力的「怎么调用」一句——按形态给通用调用机制，不写死具体技能（D22 反盲盒）。
    Skill：任务相关时按 frontmatter description 自动加载，也可点名；MCP/代码/配置各有入口。
    form 缺失默认 Skill。"""
    f = (form or "Skill").strip()
    if f == "MCP":
        return "配进 Claude Code 后自动暴露工具，模型按需调"
    if f == "repo":
        return "cd 进克隆目录，按其 README 装依赖+配置+运行"
    if f in ("代码", "code", "Code"):
        return "按其说明引入/运行的代码片段"
    if f in ("配置", "config", "Config"):
        return "按其说明并入 Claude Code 设置"
    return f"任务相关时自动加载；或点名『使用 {name} 技能』"


def _prereq_text(item: dict) -> str:
    """「装完前必做」列内容：从 item 的 usability/credential_env/post_install_steps 取（D22 反黑箱）。
    install_list.json 每条 item 都带这三个字段（verify 阶段 catalog 写入）；Skill 旧 item 无则回退「装完即用」。"""
    if not item:
        return "—"
    u = (item.get("usability") or "ready").strip()
    creds = item.get("credential_env") or []
    if isinstance(creds, str):
        creds = [creds]
    steps = item.get("post_install_steps") or []
    joined = "；".join(steps)
    parts: list[str] = []
    # needs_credentials：凭证是硬前提——若 post_install_steps 已点出则不重复，否则单独标
    if u == "needs_credentials" and creds and not any(c in joined for c in creds):
        parts.append("必须配 " + "、".join(f"`{c}`" for c in creds) + "（否则装了调不通）")
    for st in steps:
        parts.append(st.replace("|", "/").replace("\n", " "))
    if not parts:
        return "—（装完即用）" if u == "ready" else f"（{u}）"
    return "；".join(parts)


def _rollback_mcp_lines(names: list[str]) -> list[str]:
    """MCP 形态回滚：claude mcp remove -s user；binary 缺失则手动删 ~/.claude.json 对应 key。"""
    lines = ["# MCP 形态：从 ~/.claude.json (user scope) 注销"]
    for n in names:
        lines.append(f"claude mcp remove {n} -s user     # 或手动删 ~/.claude.json 里 mcpServers['{n}']")
    return lines


def _rollback_repo_lines(names: list[str]) -> list[str]:
    """repo（克隆即用）形态回滚：删克隆目录 ~/.claude/clones/<name>；台账同步移除。"""
    lines = ["# repo 形态：删克隆目录（install_path 默认 ~/.claude/clones/<name>）"]
    for n in names:
        lines.append(f"rm -rf ~/.claude/clones/{n}     # 克隆目录连同依赖一起删；台账另 registry.remove_skill 删登记")
    return lines


def _provenance_label(p: str) -> str:
    """装法来源中文映射（D23 反盲盒）。installer.py 写的 provenance 取值：
    cache/catalog/ai/ai_unverified/unresolved（installer.py cache_lookup 命中
    后 provenance 改写为 "cache" 而非 "cached"，这里对齐）。"""
    return {
        "cache": "缓存命中",
        "catalog": "catalog 种子",
        "ai": "AI 推断（已验证）",
        "ai_unverified": "AI 推断（未验证）",
        "unresolved": "未解析",
    }.get(p, p or "未知")


def _d22_invoke_section(g: dict, *, heading: str) -> list[str]:
    """D22 反盲盒·透明可追：本次（待）落盘的能力逐个说清「是什么 / 怎么调用 / 装完前必做」——
    @名 + description（MCP 取 invoke_hint/capability_name）里的触发提示词 + 调用机制 + 装完前必做
    （usability/凭证/后续步骤）。与 §1 落地清单同口径取 new_installed；form 取自台账 active 行（dry-run 无则取 item）。
    dry-run 未落盘**也列候选**（D22 反盲盒：装之前就说清要配啥，不是装完才发现调不通）。
    这是 R1（装了不自动调用）痛点的 MVP 桥接：报告说清调用方式 + 前置，人照着调，完整自动调度留 v2+。"""
    out: list[str] = []
    inst = g["new_installed"]
    really = bool(g.get("src_sessions"))
    rec = g.get("recommend")
    by_name = g["by_name"]
    reg = g["reg_active_by_name"]
    rt = g.get("resolve_trace") or {}
    rt_items = rt.get("items", {})

    out.append(heading)

    # D23: unresolved 小节——无论有无 new_installed，都应展示哪些能力暂未纳入（反盲盒透明）
    unresolved = rt.get("unresolved") if "unresolved" in rt else g.get("il", {}).get("unresolved", [])

    if not inst and not unresolved:
        out.append("（本批无 new 能力候选，无可调用项。）")
        out.append("")
        return out

    if inst:
        if really:
            out.append("本次落盘的能力**装完就能用**——下表逐个说清「怎么唤起 / 怎么调用 / 装完前必做」，"
                       "装了一堆也不会「不知道怎么调」（D22 反盲盒 / R1 痛点 MVP 桥接）。")
        else:
            out.append("本次 dry-run（未 `--approve`）**未落盘**——但仍逐个列出每个候选的"
                       "「怎么唤起 / 怎么调用 / **装完前必做**」（D22 反盲盒：装之前就看清哪些要配凭证/改配置/首跑下载，"
                       "而不是装完才发现调不通）。`--approve` 真正装上后此表即已装清单。")
        out.append("")
        out.append("| # | @名 | 形态 | 装法来源 | 触发提示词（怎么唤起它） | 怎么调用（机制） | 装完前必做 |")
        out.append("|---|-----|------|----------|--------------------------|------------------|------------|")
        for i, d in enumerate(inst, 1):
            name = d["name"]
            s = by_name.get(name, {})
            r = reg.get(name, {})
            disp = s.get("display_name") or r.get("display_name") or name
            form = r.get("form") or s.get("form") or d.get("form") or "Skill"
            trig_src = s.get("description") or s.get("invoke_hint") or s.get("capability_name") or ""
            prereq = _prereq_text(s)
            meta = rt_items.get(name, {})
            prov = _provenance_label(meta.get("provenance", ""))
            out.append(f"| {i} | `{disp}` | {form} | {prov} | {_trigger(trig_src)} "
                       f"| {_invoke_hint(disp, form)} | {prereq} |")
        out.append("")
        out.append("> **调用方式速记**：Skill 形态的能力，Claude Code 在任务相关时按每个技能 frontmatter "
                   "的 `description` 自动加载（无需手输 `@`）；想强制用某个，直接说『使用 `<名>` 技能』。"
                   "「触发提示词」列即每个技能 description 里的 `Use when…` 条件——满足时自动唤起。"
                   "MCP 形态配进 `~/.claude.json` 后自动暴露工具，模型按需调；「装完前必做」列点明凭证/配置/首跑。"
                   "repo（克隆即用）形态 clone 到 `~/.claude/clones/` 后，`cd` 进去按其 README 装依赖+配置+运行；"
                   "本工具只负责克隆+装依赖，真跑还得配齐凭证/运行时，见「装完前必做」列。")
        if rec:
            out.append(f"> 注：install 实装 `approved` 子集（D20 挑着买，{len(rec.get('approved', []))} 个）；"
                       f"上表按 §1 口径列全量 new 候选，供逐个查调用方式与前置。")
    else:
        out.append("（本批无 new 能力候选，无可调用项。）")
        out.append("")

    # D23: unresolved 小节——哪些能力因缺信息/凭证/装法暂未纳入安装计划
    if unresolved:
        out.append("")
        out.append("### 未解析 (unresolved) —— 暂未纳入安装计划")
        out.append("")
        out.append("以下能力因缺少装法信息或凭证，本次**未安装**。补齐缺失项后重新跑 `verify` 再装：")
        out.append("")
        out.append("| 名 | 卡点原因 | 缺失项 |")
        out.append("|-----|----------|--------|")
        for u in unresolved:
            name = u.get("name") or "?"
            reason = u.get("reason") or "装法未知（catalog 无此条目，AI 推断也未能确定装法）"
            missing = u.get("missing") or []
            missing_str = "、".join(f"`{m}`" for m in missing) if missing else "—"
            out.append(f"| `{name}` | {reason} | {missing_str} |")
        out.append("")
    out.append("")
    return out


# ---- 生成 RECORD.md（安装台账记录）----

def _gen_record(g: dict) -> str:
    L: list[str] = []
    full = g["full_name"]
    src_sessions = g["src_sessions"]
    latest = src_sessions[-1] if src_sessions else None
    inst = g["new_installed"]
    active = g["active"]
    merged = g["merged"]
    # G3 finding-2：sessions=0（dry-run 未 --approve）时 inst=dedup-new 是「候选」非「已装」；
    # G2 判断步产物（跑了 recommend 才有，没跑 None → 优雅降级，D19/D22）
    really_installed = bool(src_sessions)
    rec = g.get("recommend")

    L.append(f"# 安装台账记录 · {g['source_dir'].name}（代码生成）\n")
    src_label = _source_label(g['source_dir'].name)
    if full:
        L.append(f"> **源素材**：{src_label} `{g['source_dir'].name}` · **一手仓库**：`{full}`"
                 f"（{g['star_tag']}，MIT 许可证）")
    elif g["src_form"] == "repo":
        # repo（克隆即用）：install_list 无 verified_repo 键，身份取首个 item
        # （full_name 为空，勿误报「MIT 许可证」；星数从 item 取，非 g["star_tag"]）
        ri = g["repo_item"]
        if ri and g["total"] == 1:
            creds = ri.get("credential_env") or []
            cred_txt = ("，需配 " + "、".join(f"`{c}`" for c in creds)) if creds else "，装完即用"
            L.append(f"> **源素材**：{src_label} `{g['source_dir'].name}` · **形态**：repo（克隆即用）"
                     f" · **一手仓库**：`{ri.get('repo','')}`（{_star_tag(ri)}{cred_txt}）")
        else:
            L.append(f"> **源素材**：{src_label} `{g['source_dir'].name}` · **形态**：repo（克隆即用）"
                     f"（{g['total']} 个独立仓库，每项自带上游仓与星数）")
    else:
        # MCP 多源：无单一仓库，install_list 各 item 自带 repo/stars（D2 产物形态/源皆不预设）
        L.append(f"> **源素材**：{src_label} `{g['source_dir'].name}` · **形态**：MCP"
                 f"（{g['total']} 个独立能力，每项自带上游仓与星数）")
    if latest:
        L.append(f"> **本次执行**：`{latest.get('authorization_choice','')}` · "
                 f"**会话时间**：{latest.get('installed_at','')}（代码 install）")
        L.append(f"> **结果**：✅ **{latest.get('skills_before','?')} → "
                 f"{latest.get('skills_after','?')} 个 distinct 能力**"
                 f"（+{latest.get('skills_added',0)} 新增）\n")
    L.append("---\n")

    # 0. 一句话
    n_inst = len(inst)
    in_prog = [d for d in inst if d.get("category") == "in-progress"]
    personal = [d for d in inst if d.get("category") == "personal"]
    forms = {(d.get("form") or "Skill") for d in inst}
    has_mcp = "MCP" in forms
    has_skill = "Skill" in forms
    has_repo = "repo" in forms
    if has_repo:
        install_verb = "git clone 仓到 `~/.claude/clones/` + 装依赖（阿里云镜像）+ 配置后运行"
    elif has_mcp and has_skill:
        install_verb = "Skill 整目录拷到 `.claude/skills/` + MCP 注册进 `~/.claude.json`"
    elif has_mcp:
        install_verb = "MCP 注册进 `~/.claude.json`（user scope，`claude mcp add -s user`）"
    else:
        install_verb = "整目录从 GitHub raw 拷到本机 `.claude/skills/`"
    L.append("## 0. 一句话\n")
    if really_installed:
        L.append(f"代码 `install --approve` 落地：照 dedup 判定的 new 能力（去掉 deprecated），"
                 f"{install_verb}，本次新装 **{n_inst}** 个、"
                 f"整并 **0** 个（merge 候选留人工确认，不自动并）、登记进 SQLite 台账；"
                 f"磁盘 active distinct **{g['disk_distinct']}** == 台账 active **{len(active)}**，"
                 f"你落盘就是什么。\n")
    else:
        L.append(f"**dry-run（未 `--approve`）**：照 dedup 判定有 **{n_inst}** 个 new 候选，"
                 f"但本次未授权安装、未落盘、未登记台账——是「待装候选」非「已装」。"
                 f"磁盘 active distinct **{g['disk_distinct']}** == 台账 active **{len(active)}**（基准未动）。\n")

    # 1. 落地清单（形态感知：Skill 列文件数，MCP 列包/命令 + scope）
    L.append("## 1. 落地清单\n")
    if really_installed:
        parts = []
        if has_skill:
            parts.append("写入 `~/.claude/skills/`")
        if has_mcp:
            parts.append("注册 `~/.claude.json`")
        if has_repo:
            parts.append("克隆 `~/.claude/clones/`")
        where = " + ".join(parts)
        L.append(f"### 本次新装 {n_inst} 个能力（{where}）\n")
    else:
        L.append(f"### 待装候选 {n_inst} 个能力（dedup 判 new，尚未 `--approve` 落盘）\n")
    if has_repo and not has_mcp and not has_skill:
        L.append("| # | 能力名 | 形态 | 上游仓 | 星数 | 凭证 | 一句话 |")
        L.append("|---|--------|------|--------|------|------|--------|")
        for i, d in enumerate(inst, 1):
            name = d["name"]
            s = g["by_name"].get(name, {})
            form = d.get("form") or s.get("form") or "repo"
            repo_full = s.get("repo") or d.get("repo") or ""
            stars = s.get("stars") if s.get("stars") is not None else d.get("stars")
            star_txt = f"⭐{stars}" if stars is not None else "（星数未取）"
            creds = s.get("credential_env") or d.get("credential_env") or []
            cred_txt = ("、".join(f"`{c}`" for c in creds)) if creds else "—"
            desc = _short(s.get("invoke_hint") or s.get("description", ""))
            L.append(f"| {i} | `{name}` | {form} | `{repo_full}` | {star_txt} | {cred_txt} | {desc} |")
    elif has_mcp and not has_skill:
        L.append("| # | 能力名 | 形态 | 注册方式 | 包/命令 | 一句话 |")
        L.append("|---|--------|------|----------|---------|--------|")
        for i, d in enumerate(inst, 1):
            name = d["name"]
            s = g["by_name"].get(name, {})
            form = d.get("form") or s.get("form") or "MCP"
            mcp = s.get("mcp") or {}
            cmd = mcp.get("command", "")
            args = " ".join(mcp.get("args", []))
            scope = mcp.get("scope", "user")
            pkg = f"`{cmd} {args}`".replace("|", "/") if cmd else (s.get("repo") or "")
            desc = _short(s.get("invoke_hint") or s.get("capability_name") or s.get("description", ""))
            L.append(f"| {i} | `{name}` | {form} | {scope} | {pkg} | {desc} |")
    else:
        L.append("| # | 目录名 | 形态 | 分类 | 文件数 | 一句话 |")
        L.append("|---|--------|------|------|--------|--------|")
        for i, d in enumerate(inst, 1):
            name = d["name"]
            s = g["by_name"].get(name, {})
            reg = g["reg_active_by_name"].get(name, {})
            form = d.get("form") or s.get("form") or "Skill"
            cat = d.get("category") or s.get("category", "")
            files = reg.get("file_count") or s.get("file_count", "?")
            desc = _short(s.get("description", ""))
            L.append(f"| {i} | `{name}` | {form} | {cat} | {files} | {desc} |")
    L.append("")
    if in_prog or personal:
        L.append(f"> ⚠️ **诚实提示**：这 {n_inst} 个里有 **{len(in_prog)} 个 in-progress（未完成）**"
                 f" + **{len(personal)} 个 personal（作者个人）** 能力。")
        if rec:
            L.append(f"> dedup 只判「是否重复」；判断步(recommend·{rec.get('mode','?')}模式) 已补判「是否值得装」——"
                     f"in-progress/personal 多判为不值得装，approved={len(rec.get('approved', []))} 才该装"
                     f"（D20 挑着买，verdict 分布见看板 §2）。")
        else:
            L.append(f"> 代码去重只判「是否重复」（名字/描述重叠），**不判「是否值得装」**，"
                     f"且只默认排除 `deprecated`；手动 REPORT.md 曾把 in-progress / personal 标「跳过·不装」。")
        if really_installed:
            L.append(f"> 若不需要，见 §6 回滚逐个删，或后续给 install 加 `--exclude-categories in-progress,personal`。\n")
        else:
            L.append(f"> 本次 dry-run 未安装、无需回滚；可先跑 recommend 判断步筛掉，或 install 加"
                     f" `--exclude-categories in-progress,personal`。\n")

    # 2. 能力台账
    L.append("## 2. 能力台账（SQLite）\n")
    L.append(f"- **库**：`data/registry.db`（`skillbrew/registry.py`，schema = `skills` + `install_sessions`）")
    L.append(f"- **skills 表**：{len(g['all_skills'])} 行（active {len(active)} + merged {len(merged)}）")
    L.append(f"- **install_sessions 表**：{len(src_sessions)} 条本源安装会话\n")
    L.append("**按来源（active+merged）**：\n")
    L.append("| 来源 | active | merged | 合计 |")
    L.append("|------|--------|--------|------|")
    by_src_active = _by_field(active, "source")
    by_src_merged = _by_field(merged, "source")
    for src in sorted(set(by_src_active) | set(by_src_merged)):
        a = by_src_active.get(src, 0)
        m = by_src_merged.get(src, 0)
        L.append(f"| {src} | {a} | {m} | {a + m} |")
    L.append("")
    L.append("**按分类（active）**：\n")
    L.append("| 分类 | active |")
    L.append("|------|--------|")
    for cat, n in sorted(_by_field(active, "category").items(), key=lambda x: -x[1]):
        L.append(f"| {cat} | {n} |")
    L.append("")
    if src_sessions:
        L.append("**本源安装会话（累计轨迹）**：\n")
        L.append("| # | 授权选择 | before | added | merged | after | 时间 |")
        L.append("|---|----------|--------|--------|--------|-------|------|")
        for i, s in enumerate(src_sessions, 1):
            L.append(f"| {i} | {s.get('authorization_choice','')} | {s.get('skills_before','?')} | "
                     f"{s.get('skills_added','?')} | {s.get('skills_merged','?')} | "
                     f"{s.get('skills_after','?')} | {s.get('installed_at','')} |")
        L.append("\n> 注：两次会话的 before/after 口径略有不同——第 1 次（手动 A）按 active 计"
                 "（merged 的 tdd 不计入 after=40）；第 2 次（代码 --approve）按 distinct 计"
                 "（含 merged，before=41/after=54）。最终台账统一口径为 distinct = "
                 f"{len(g['all_skills'])}（active {len(active)} + merged {len(merged)}）。\n")

    # 3. 去重整并结果
    summ = g["summary"]
    L.append("## 3. 去重整并结果（来自 dedup.json）\n")
    L.append("| 判定 | 数 | 处置 |")
    L.append("|------|----|------|")
    new_dispose = f"代码装 {len(inst)}" if really_installed else f"候选 {len(inst)}（未 --approve）"
    L.append(f"| new（新装）| {summ.get('new',0)} | {new_dispose}；deprecated 跳 {len(g['new_deprecated'])} |")
    L.append(f"| merge（建议整并）| {summ.get('merge',0)} | 不自动装，留人工确认 |")
    L.append(f"| skip（已装/已整并）| {summ.get('skip',0)} | 不动 |")
    L.append(f"| **合计** | **{summ.get('total',0)}** | 全仓 {g['total']} 个能力 |")
    L.append("")
    if g["merge_cands"]:
        L.append("**merge 候选（建议人工确认整并，未自动决定）**：\n")
        for d in g["merge_cands"]:
            sh = ", ".join(d.get("shared", []))
            L.append(f"- `{d['name']}` → `{d.get('target','')}`  〔共享词：{sh}〕")
        L.append("")

    # 4. 落盘核对
    L.append("## 4. 落盘核对（你落盘就是什么）\n")
    L.append(f"实时扫磁盘 vs 台账 active（扫描目录：{[str(d) for d in g['skill_dirs']]}；"
             f"MCP 读 `~/.claude.json` 注册表）：\n")
    L.append(f"- 磁盘 active distinct：**{g['disk_distinct']}**"
             f"（Skill 目录 {g['disk_skill_distinct']} + MCP 注册 {g['disk_mcp_count']}）")
    L.append(f"- 台账 active：**{len(active)}**"
             f"（Skill {len(g['reg_active_skill'])} + MCP {len(g['reg_active_mcp'])}）")
    L.append(f"- 孤儿（磁盘有 / 台账无）：{len(g['orphans'])} 个"
             + (f" → {g['orphans']}" if g["orphans"] else ""))
    L.append(f"- 缺失（台账有 / 磁盘无）：{len(g['missing'])} 个"
             + (f" → {g['missing']}" if g["missing"] else ""))
    if g["disk_distinct"] == len(active) and not g["orphans"] and not g["missing"]:
        L.append("\n✅ **一致：磁盘落盘 == 台账登记**。\n")
    else:
        L.append("\n⚠️ **不一致**：以上孤儿/缺失需处理（台账与磁盘对不齐）。\n")

    # 5. before/after 可视化
    L.append("## 5. before / after 可视化\n")
    L.append("```mermaid")
    L.extend(_cumulative_flow(g["src_sessions"], active, merged))
    L.append("```\n")
    L.append("```mermaid")
    L.append("pie title 台账 active 能力来源构成")
    for src, n in sorted(by_src_active.items(), key=lambda x: -x[1]):
        L.append(f'    "{src}" : {n}')
    L.append("```\n")

    # 6. 可移除 / 回滚（形态感知：Skill rm -rf 目录、MCP claude mcp remove）
    L.append("## 6. 可移除 / 回滚\n")
    if really_installed:
        sess0_added = src_sessions[0].get("skills_added", "?") if src_sessions else "?"
        L.append(f"若要卸载本次代码安装的 {n_inst} 个能力"
                 f"（不影响手动 A 装的 {sess0_added} 个和本机原有）：\n")
        skill_names = [d["name"] for d in inst if (d.get("form") or "Skill") == "Skill"]
        mcp_names = [d["name"] for d in inst if (d.get("form") or "Skill") == "MCP"]
        repo_names = [d["name"] for d in inst if (d.get("form") or "Skill") == "repo"]
        L.append("```bash")
        if skill_names:
            L.append("# Skill 形态：删 ~/.claude/skills 下的目录")
            L.append("cd ~/.claude/skills")
            for i in range(0, len(skill_names), 4):
                L.append("rm -rf " + " ".join(skill_names[i:i + 4]))
        if mcp_names:
            if skill_names:
                L.append("")
            L.extend(_rollback_mcp_lines(mcp_names))
        if repo_names:
            if skill_names or mcp_names:
                L.append("")
            L.extend(_rollback_repo_lines(repo_names))
        L.append("```\n")
        L.append("台账移除：`registry.remove_skill(conn, name)` 逐个删，或直接删 `data/registry.db` 重建。\n")
    else:
        L.append(f"本次 dry-run（未 `--approve`）**未安装任何能力**——磁盘与台账均未动，无需回滚。\n")
        L.append(f"若日后 `--approve` 装了再想卸载，本节会列 `rm -rf`（Skill）/ `claude mcp remove`（MCP）"
                 f"/ `rm -rf ~/.claude/clones/`（repo）清单 + 台账移除法。\n")

    # 7. 开源合规（形态感知：Skill 单仓 MIT / MCP 各包许可 / repo 各仓各自许可）
    L.append("## 7. 开源合规\n")
    if full:
        L.append(f"- **仓库**：{g['html_url']}（MIT License）—— 允许再分发，须保留版权与许可声明。")
        L.append(f"- **本机落地**：每个新增能力保留原作者原文；台账 `attribution` 字段登记 "
                 f"「{full}（GitHub 开源）」。")
        L.append(f"- **定位方式**：{g['how_resolved']}\n")
    elif g["src_form"] == "repo":
        # repo（克隆即用）：install_list 无 verified_repo 键，full_name 为空；
        # 合规按各 item 上游仓取数（D2 不预设形态/源，勿误走 MCP 分支）
        ri = g["repo_item"]
        if ri and g["total"] == 1:
            L.append(f"- **仓库**：`{ri.get('repo','')}`（{_star_tag(ri)}）—— 按其各自上游许可"
                     "（多为 MIT / Apache-2.0）；clone 下来本地跑须保留版权与许可声明。")
            L.append("- **本机落地**：git clone 整仓保留原作者原文；install 仅 clone + 装依赖 + 配置，"
                     "不改上游、不分发。")
            L.append("- **归属**：item 的 `repo`/`url` 字段登记上游仓，台账 `attribution` 留痕；"
                     "定位方式=verify probe_repo 直接核 GitHub API。\n")
        else:
            L.append("- **repo 形态**：各仓按各自上游许可；install 仅 clone + 装依赖 + 配置，不改上游。")
            L.append("- **归属**：每个 item 的 `repo` 字段登记上游仓，台账 `attribution` 留痕。\n")
    else:
        L.append("- **MCP 形态**：各包按各自上游许可（多为 MIT / Apache-2.0）；install 仅注册到 "
                 "`~/.claude.json`，不拷源码、不改上游。")
        L.append("- **归属**：每个 item 的 `repo` 字段登记上游仓，台账 `attribution` 留痕；"
                 "catalog（brew-formula 表，D20 非硬编码 install_steps）定位，未命中者进 unresolved 透明降级。\n")

    # 8. 怎么调用装好的技能（D22 反盲盒 / R1 痛点 MVP 桥接）
    L.extend(_d22_invoke_section(g, heading="## 8. 怎么调用装好的技能（D22 · 反盲盒）\n"))

    L.append("---\n")
    L.append(f"*本记录 = skillbrew Step 5「记录 + 看板」代码生成产物（{_today()}）。"
             f"所有数字来自实时台账/磁盘/清单，非手写。*\n")
    return "\n".join(L)


# ---- 生成 DASHBOARD.md（本次 + 累计看板）----

def _gen_dashboard(g: dict) -> str:
    L: list[str] = []
    full = g["full_name"]
    src_sessions = g["src_sessions"]
    active = g["active"]
    summ = g["summary"]
    inst = g["new_installed"]
    src_form = g["il"].get("form") or "Skill"
    has_mcp = src_form == "MCP"  # §1 溯源纠错据此剥 Skill 路径残留 boilerplate（D2 不退化成 Skill 加载器）
    has_repo = src_form == "repo"  # repo（克隆即用）：身份取 g["repo_item"]，勿误走 MCP 分支（full_name 为空）
    # G3 finding-2 / G2 判断步：与 _gen_record 同口径（基准零回归、dry-run 降级、recommend 优雅接入）
    really_installed = bool(src_sessions)
    rec = g.get("recommend")

    L.append(f"# 安装看板 · {g['source_dir'].name}（本次 + 累计，代码生成）\n")
    src_label = _source_label(g['source_dir'].name)
    if full:
        L.append(f"> **源素材**：{src_label} `{g['source_dir'].name}` · **一手仓库**：`{full}`（{g['star_tag']}）")
    elif has_repo:
        ri = g["repo_item"]
        if ri and g["total"] == 1:
            L.append(f"> **源素材**：{src_label} `{g['source_dir'].name}` · **形态**：repo（克隆即用）"
                     f" · **一手仓库**：`{ri.get('repo','')}`（{_star_tag(ri)}）")
        else:
            L.append(f"> **源素材**：{src_label} `{g['source_dir'].name}` · **形态**：repo（克隆即用）"
                     f"（{g['total']} 个独立仓库）")
    else:
        L.append(f"> **源素材**：{src_label} `{g['source_dir'].name}` · **形态**：MCP（{g['total']} 个独立能力）")
    L.append(f"> **本源安装会话**：{len(src_sessions)} 次 · **当前台账**："
             f"{len(g['all_skills'])} distinct（active {len(active)} + merged {len(g['merged'])}）\n")
    L.append("---\n")

    # 0. 一句话
    L.append("## 0. 一句话\n")
    if full:
        L.append(f"一条{src_label}视频 → 顺藤摸瓜定位 `{full}`（{g['total']} 个能力）"
                 f"→ 去重判定 → 授权安装累加：{_session_arrows(src_sessions)}，"
                 f"越装越强没塞重复；磁盘 active distinct {g['disk_distinct']} == 台账 {len(active)}。\n")
    elif has_repo:
        L.append(f"一条{src_label}视频 → 消化出 {g['total']} 个 repo（克隆即用）项目候选 → 去重判定"
                 f" → 授权 clone+装依赖+配置：{_session_arrows(src_sessions)}，"
                 f"越装越强没塞重复；磁盘 active distinct {g['disk_distinct']} == 台账 {len(active)}。\n")
    else:
        L.append(f"一条{src_label}视频 → 消化出 {g['total']} 个 MCP 能力候选 → 去重判定"
                 f" → 授权安装累加：{_session_arrows(src_sessions)}，"
                 f"越装越强没塞重复；磁盘 active distinct {g['disk_distinct']} == 台账 {len(active)}。\n")

    # 1. 顺藤摸瓜追踪图（节点文字全从一手数据现取，不写死 BV 号/错仓库名/星数）
    L.append("## 1. 顺藤摸瓜追踪图\n")
    src_name = g["source_dir"].name
    ocr_fix_text = (g["verify_corrections"][0] if g["verify_corrections"]
                    else "草稿 OCR 误记 → 一手核实纠正")
    ocr_fix_short = ocr_fix_text.removeprefix("summary: ").replace('"', "'").replace("\n", " ")
    L.append("```mermaid")
    L.append("flowchart LR")
    if full:
        vf_label = f"真身 {full}"
    elif has_repo:
        ri = g["repo_item"]
        vf_label = f"真身 {ri.get('repo', '')}" if ri else "repo 探测定位"
    else:
        vf_label = "MCP catalog 定位"
    L.append(f'    V["素材<br/>{src_label} {src_name}"] --> P["消化草稿<br/>plan.json（OCR）"]')
    L.append(f'    P -->|"{ocr_fix_short}"| VF["溯源核实<br/>{vf_label}"]')
    L.append(f'    VF --> IL["一手安装清单<br/>{g["total"]} 个能力"]')
    L.append('    IL --> DD["去重判定<br/>new / merge / skip"]')
    if src_sessions:
        for i, s in enumerate(src_sessions):
            lbl = _session_label(i, s.get("authorization_choice", ""))
            before = s.get("skills_before", "?")
            after = s.get("skills_after", "?")
            L.append(f'    DD --> S{i+1}["{lbl}<br/>{before} → {after}"]')
            L.append(f'    S{i+1} --> R')
    else:
        L.append('    DD --> R')
    L.append(f'    R["能力台账<br/>{len(g["all_skills"])} distinct"]')
    L.append("    classDef fix fill:#fff3cd,stroke:#b8860b;")
    L.append("    class VF fix;")
    L.append("```\n")
    if g["ocr_note"]:
        note = g["ocr_note"]
        if has_mcp or has_repo:
            # 非 Skill 形态（MCP / repo）：traced note 尾部「全仓 N 个 skill 详见 install_list.json」是
            # verify 的 Skill 路径残留 boilerplate（单仓 resolve_repo 只数 SKILL.md），对 MCP/repo 无意义——
            # §1 表/§2 已列 N 个能力。剥掉避免「退化成 Skill 加载器」措辞（D2 产物形态由计划内容决定，不预设）。
            idx = note.find("全仓")
            if idx >= 0 and "skill 详见 install_list.json" in note[idx:]:
                note = note[:idx].rstrip().rstrip("。").rstrip()
        L.append(f"**溯源纠错**（plan.json 一手留痕）：{note}\n")
    else:
        if full:
            L.append(f"**溯源纠错**：verify 回 GitHub 一手核实为 `{full}`（{g['star_tag']}）。\n")
        elif has_repo:
            ri = g["repo_item"]
            repo_txt = ri.get("repo", "") if ri else ""
            star_txt = _star_tag(ri) if ri else "（星数未取）"
            L.append(f"**溯源纠错**：verify probe_repo 直核 GitHub API 定位 `{repo_txt}`（{star_txt}）。\n")
        else:
            L.append("**溯源纠错**：MCP 形态，各 item 按 catalog（brew-formula 表）定位上游包，未命中者进 unresolved 透明降级。\n")

    # 2. 全仓 skill 决策分布
    L.append(f"## 2. 全仓 {g['total']} 个能力装不装（dedup 判定）\n")
    L.append("```mermaid")
    L.append("pie title 全仓能力处置分布")
    L.append(f'    "跳过·已装(手动A)" : {len(g["skips"])}')
    _new_label = "代码本次新装" if really_installed else "代码本次新装候选"
    L.append(f'    "{_new_label}" : {len(inst)}')
    L.append(f'    "跳过·deprecated" : {len(g["new_deprecated"])}')
    L.append(f'    "跳过·建议整并(merge)" : {len(g["merge_cands"])}')
    L.append("```\n")
    skip_merged = sum(1 for d in g["skips"] if "已整并" in (d.get("reason") or ""))
    skip_installed = len(g["skips"]) - skip_merged
    L.append(f"- **skip {len(g['skips'])}**：手动 A 已装 {skip_installed} 个 + 已整并 {skip_merged} 个"
             f"（dedup 基准命中）")
    if really_installed:
        L.append(f"- **新装 {len(inst)}**：本次代码 `--approve` 整目录拷下来的")
    else:
        L.append(f"- **待装候选 {len(inst)}**：dedup 判 new，dry-run 未 `--approve`、未拷盘")
    L.append(f"- **deprecated {len(g['new_deprecated'])}**：仓库标废弃，默认跳（`--include-deprecated` 才装）"
             + (f" → {[d['name'] for d in g['new_deprecated']]}" if g["new_deprecated"] else ""))
    L.append(f"- **merge {len(g['merge_cands'])}**：描述重叠≥3 词，建议人工整并，不自动决定\n")

    # G2 判断步(recommend)：跑了才有，没跑优雅降级（D19 判断先行 / D22 反盲盒）
    if rec:
        rsumm = rec.get("summary", {})
        by_v = rsumm.get("by_verdict", {})
        approved = rec.get("approved", [])
        L.append(f"\n**判断步（recommend·{rec.get('mode','?')}模式）**：dedup 只判「是否重复」，"
                 f"本步补判「是否值得装」（D19）。源级建议：**{rec.get('source_verdict','?')}**。\n")
        L.append("```mermaid")
        L.append("pie title 判断步 verdict 分布")
        for _v in ("值得装", "不值得装", "建议整并", "已装"):
            if by_v.get(_v):
                L.append(f'    "{_v}" : {by_v[_v]}')
        L.append("```\n")
        L.append(f"- **值得装 {by_v.get('值得装', 0)}** → approved（install 只装这些，D20 挑着买）")
        L.append(f"- **不值得装 {by_v.get('不值得装', 0)}**：未完成/个人用/与本机重叠等，跳过")
        L.append(f"- **建议整并 {by_v.get('建议整并', 0)}**：留人工确认，不自动决定")
        L.append(f"- **已装 {by_v.get('已装', 0)}**：dedup 判 skip，无需再装")
        if rec.get("source_skip_reason"):
            L.append(f"- **整源跳过**：{rec['source_skip_reason']}（approved 已置空，install 不装）")
        L.append(f"\n> approved 子集 = **{len(approved)}** 个（从 {len(inst)} 个 new 候选里挑出）。"
                 f"{'本次 dry-run 未装；`--approve` 后 install 只装这批。' if not really_installed else 'install 据此 approved 落地。'}\n")

    # 3. 去重比对
    L.append("## 3. 去重比对（merge 候选）\n")
    if g["merge_cands"]:
        L.append("| 候选 | 建议整并进 | 共享词 |")
        L.append("|------|-----------|--------|")
        for d in g["merge_cands"]:
            L.append(f"| `{d['name']}` | `{d.get('target','')}` | {', '.join(d.get('shared', []))} |")
        L.append("\n> 跨语种语义整并（如英文 tdd ↔ 中文 Python测试技能）非纯标准库可判，"
                 "tdd 已在手动 A 时人工整并（台账 status=merged）。\n")
    else:
        L.append("无 merge 候选。\n")

    # 4. 累加 before/after（两次会话）
    L.append("## 4. 累加可视化（两次会话）\n")
    L.append("```mermaid")
    L.extend(_cumulative_flow(g["src_sessions"], active, g["merged"]))
    L.append("```\n")
    L.append("**会话明细**：\n")
    L.append("| # | 授权 | before → after | 新增 | 整并 |")
    L.append("|---|------|----------------|------|------|")
    for i, s in enumerate(src_sessions, 1):
        L.append(f"| {i} | {s.get('authorization_choice','')} | "
                 f"{s.get('skills_before','?')} → {s.get('skills_after','?')} | "
                 f"+{s.get('skills_added',0)} | +{s.get('skills_merged',0)} |")
    L.append("")
    L.append("```mermaid")
    L.append("pie title 台账 active 能力来源构成")
    by_src = _by_field(active, "source")
    for src, n in sorted(by_src.items(), key=lambda x: -x[1]):
        L.append(f'    "{src}" : {n}')
    L.append("```\n")
    L.append("```mermaid")
    L.append("pie title 台账 active 能力分类构成")
    by_cat = _by_field(active, "category")
    for cat, n in sorted(by_cat.items(), key=lambda x: -x[1]):
        L.append(f'    "{cat}" : {n}')
    L.append("```\n")

    # 5. 落盘完整性核对
    L.append("## 5. 落盘完整性核对（你落盘就是什么）\n")
    ok = g["disk_distinct"] == len(active) and not g["orphans"] and not g["missing"]
    L.append(f"- 磁盘 active distinct：**{g['disk_distinct']}**")
    L.append(f"- 台账 active：**{len(active)}**")
    L.append(f"- 孤儿（磁盘有/台账无）：{len(g['orphans'])}"
             + (f" → {g['orphans']}" if g["orphans"] else ""))
    L.append(f"- 缺失（台账有/磁盘无）：{len(g['missing'])}"
             + (f" → {g['missing']}" if g["missing"] else ""))
    L.append(f"\n{'✅ 一致：落盘 == 台账。' if ok else '⚠️ 不一致，见孤儿/缺失。'}\n")

    # 6. 诚实提示
    in_prog = [d for d in inst if d.get("category") == "in-progress"]
    personal = [d for d in inst if d.get("category") == "personal"]
    L.append("## 6. 诚实提示（本次代码安装的取舍）\n")
    if really_installed:
        L.append(f"本次 `--approve` 装的 {len(inst)} 个里，有 **{len(in_prog)} 个 in-progress**"
                 f"（未完成）+ **{len(personal)} 个 personal**（作者个人用）：\n")
    else:
        L.append(f"本次 dedup 判 new 的 **{len(inst)} 个待装候选**里，有 **{len(in_prog)} 个 in-progress**"
                 f"（未完成）+ **{len(personal)} 个 personal**（作者个人用）：\n")
    if in_prog:
        L.append(f"- in-progress：{[d['name'] for d in in_prog]}")
    if personal:
        L.append(f"- personal：{[d['name'] for d in personal]}")
    L.append("")
    if rec:
        L.append(f"dedup 只判「是否重复」；判断步(recommend·{rec.get('mode','?')}模式) 已补判「是否值得装」——"
                 f"in-progress/personal 多判为不值得装，不计入 approved（{len(rec.get('approved', []))} 个）。"
                 f"{'本次 dry-run 未装、无需回滚。' if not really_installed else 'install 只装 approved 子集（D20 挑着买）。'}\n")
    else:
        L.append("代码去重只判「是否重复」，**不判「是否值得装」**，且只默认排除 `deprecated`——"
                 "所以把手动判断会跳过的未完成/个人能力也装了。这是工具当前的能力边界，"
                 "如实标出供你复核；不需要的可回滚（见 RECORD.md §6），或后续给 install 加 "
                 "`--exclude-categories`。\n")

    # 7. 怎么调用装好的技能（D22 反盲盒 / R1 痛点 MVP 桥接）
    L.extend(_d22_invoke_section(g, heading="## 7. 怎么调用装好的技能（D22 · 反盲盒）\n"))

    L.append("---\n")
    L.append(f"*本看板 = skillbrew Step 5 代码生成产物（{_today()}）。数字来自实时台账/磁盘/清单。*\n")
    return "\n".join(L)


# ---- R1 调度器 MVP：生成已装能力索引 + 非破坏性注入 CLAUDE.md ----

_INDEX_BEGIN = "<!-- skillbrew-installed-index -->"
_INDEX_END = "<!-- /skillbrew-installed-index -->"

_FRONTMATTER_DESC_RE = re.compile(
    r"^---\s*\n(?:.*?\n)*?description\s*:\s*[\"']?([^\n\"']+)[\"']?\s*\n(?:.*?\n)*?---",
    re.DOTALL,
)


def _read_skill_description(install_path: str | None) -> str:
    """从 Skill 的 SKILL.md 抠 frontmatter description 作为一行描述；读不到回退空串。"""
    if not install_path:
        return ""
    p = Path(install_path) / "SKILL.md"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return ""
    m = _FRONTMATTER_DESC_RE.match(text)
    if m:
        return m.group(1).strip()
    return ""


def _gen_installed_index(active: list[dict]) -> str:
    """生成 INSTALLED_INDEX.md 内容：Skill/MCP/repo 三段表，全量 active 能力。

    这是 charter §9.3 R1 调度器的 MVP 桥接：v3+ 前不做真正的自动调度器/cron/hook，
    只在每次 record() 后刷一份全量索引到 ~/.claude/INSTALLED_INDEX.md，
    并在 CLAUDE.md 里注入一个指向它的 sentinel 块——Claude Code 启动时会读到，
    解决「装了一堆能力但不知道有啥、怎么调」的 R1 痛点。
    """
    skills = [r for r in active if (r.get("form") or "Skill").lower() == "skill" or not r.get("form")]
    mcps = [r for r in active if (r.get("form") or "").lower() == "mcp"]
    repos = [r for r in active if (r.get("form") or "").lower() in ("repo", "repository")]
    others = [r for r in active if r not in skills and r not in mcps and r not in repos]

    L: list[str] = []
    L.append("# 已装能力索引（skillbrew 生成）\n")
    L.append("> 本文由 skillbrew 在每次 `record` 后自动刷新（R1 调度器 MVP 桥接）。"
             "完整自动调度留 v3+；此处仅列出累计所有 active 能力，"
             "供 Claude Code 启动时识别已装清单，避免「装了一堆但不知道有啥」。\n")
    L.append(f"- 生成时间：{_now_iso()}")
    L.append(f"- 累计 active 能力：{len(active)}（Skill {len(skills)} / MCP {len(mcps)} / repo {len(repos)}"
             f"{' / 其它 ' + str(len(others)) if others else ''}）")
    L.append("- 关闭本文件生成：设环境变量 `SKILLBREW_NO_INDEX=1`。\n")

    def _section(title: str, rows: list[dict]) -> None:
        L.append(f"## {title}\n")
        if not rows:
            L.append("（无）\n")
            return
        L.append("| 名字 | 形态 | 一句话说明 | 调用方式 | 路径 |")
        L.append("|------|------|------------|----------|------|")
        for r in sorted(rows, key=lambda x: (x.get("source") or "", x.get("name") or "")):
            name = r.get("display_name") or r.get("name") or "?"
            form = r.get("form") or "Skill"
            ipath = r.get("install_path") or "—"
            # 描述：registry 里有 description 优先；否则 Skill 尝试读 SKILL.md frontmatter
            desc = (r.get("notes") or "").strip()
            if not desc and form.lower() in ("skill", ""):
                desc = _short(_read_skill_description(ipath), 80)
            if not desc:
                desc = f"来源 {r.get('source') or '?'}"
            hint = _invoke_hint(name, form)
            L.append(f"| `{name}` | {form} | {_short(desc, 80)} | {hint} | `{ipath}` |")
        L.append("")

    _section("Skill（技能）", skills)
    _section("MCP 服务器", mcps)
    _section("repo（克隆即用仓库）", repos)
    if others:
        _section("其它", others)
    L.append("---\n")
    L.append(f"*本文件由 skillbrew 自动生成于 {_now_iso()}，覆盖刷新，勿手工编辑。*\n")
    return "\n".join(L)


def _update_claude_md(claude_md: Path, index_path: Path) -> None:
    """非破坏性注入/刷新 CLAUDE.md 里的 sentinel 块，指向 INSTALLED_INDEX.md。

    规则：
      - 文件不存在 → 创建，仅含 sentinel 块；
      - 已存在但无 sentinel → 末尾追加；
      - 已存在且有 sentinel → 替换块内容（幂等，不重复注入）；
      - 写入失败（权限/只读等）→ 打印提示但不抛，不中断主流程。
    """
    block = (
        f"{_INDEX_BEGIN}\n"
        f"> 以下由 skillbrew 自动维护（R1 调度器 MVP 桥接）：本环境累计已装能力索引见\n"
        f"> `{index_path}`。每次 `skillbrew record` 后自动刷新，勿手工编辑本块。\n"
        f"{_INDEX_END}\n"
    )
    try:
        if claude_md.exists():
            text = claude_md.read_text(encoding="utf-8", errors="replace")
            if _INDEX_BEGIN in text and _INDEX_END in text:
                # 替换已有块（幂等）
                pattern = re.compile(
                    re.escape(_INDEX_BEGIN) + r".*?" + re.escape(_INDEX_END) + r"\s*",
                    re.DOTALL,
                )
                new_text = pattern.sub(block, text, count=1)
            else:
                # 追加，保留用户原文
                sep = "" if text.endswith("\n") else "\n"
                new_text = text + sep + "\n" + block
        else:
            claude_md.parent.mkdir(parents=True, exist_ok=True)
            new_text = (
                "# CLAUDE.md\n\n"
                "本文件由 skillbrew 初始化，含一个自动维护的已装能力索引指针；"
                "你可在 sentinel 块外添加任意项目级指令，skillbrew 不会动它们。\n\n"
                + block
            )
        claude_md.write_text(new_text, encoding="utf-8")
    except OSError as e:
        print(f"[record] 提示：写 CLAUDE.md 失败（{e}），已装索引仍写入 {index_path}，"
              f"可手动在 CLAUDE.md 加一句『参考 {index_path}』。")


def _write_installed_index(db_path, on_progress) -> dict | None:
    """查台账全量 active → 写 INSTALLED_INDEX.md → 刷新 CLAUDE.md sentinel。

    返回 {index_path, claude_md_path, active_count}，失败返回 None 不中断主流程。
    受环境变量 SKILLBREW_NO_INDEX=1 控制——设了就完全跳过（用户主动关）。
    """
    if os.environ.get("SKILLBREW_NO_INDEX", "").strip() in ("1", "true", "TRUE", "yes"):
        if on_progress:
            on_progress("index", "skipped (SKILLBREW_NO_INDEX=1)")
        return None
    try:
        from .registry import DB_PATH, connect, list_skills
        dp = db_path or DB_PATH
        conn = connect(dp)
        try:
            active = list_skills(conn, status="active")
        finally:
            conn.close()
        home = config.claude_home()
        home.mkdir(parents=True, exist_ok=True)
        index_path = home / "INSTALLED_INDEX.md"
        claude_md = home / "CLAUDE.md"
        index_path.write_text(_gen_installed_index(active), encoding="utf-8")
        _update_claude_md(claude_md, index_path)
        if on_progress:
            on_progress("index", f"{len(active)} active → {index_path}")
        return {"index_path": str(index_path), "claude_md_path": str(claude_md),
                "active_count": len(active)}
    except Exception as e:
        # 索引导出是锦上添花，任何异常都不应该打断 record 主流程
        print(f"[record] 提示：生成已装索引失败（{e}），不影响 RECORD/DASHBOARD。")
        return None


def record(source_dir: Path, *, skill_dirs: list[Path] | None = None,
           db_path=None, on_progress=None) -> dict:
    """对一个源目录生成安装记录 + 看板：读 install_list.json / dedup.json / registry.db，
    扫磁盘，写 RECORD.md + DASHBOARD.md。返回 {record_path, dashboard_path, integrity, ...}。

    record 纯本地（台账+磁盘+清单），不调 LLM、不下载、不改台账。skill_dirs 默认
    [~/.claude/skills]；CLI 会把工作区目录一起传进来（与 dedup 同口径）。
    """
    source_dir = Path(source_dir)
    if not (source_dir / "install_list.json").exists():
        raise RuntimeError(f"没有 install_list.json，先跑 verify：{source_dir / 'install_list.json'}")
    if not (source_dir / "dedup.json").exists():
        raise RuntimeError(f"没有 dedup.json，先跑 dedup：{source_dir / 'dedup.json'}")

    if skill_dirs is None:
        # 默认用 dedup.json 自己记录的扫描目录，保证落盘核对与去重基准同口径
        dd_path = source_dir / "dedup.json"
        dd = json.loads(dd_path.read_text(encoding="utf-8"))
        dirs = dd.get("baseline", {}).get("skill_dirs", [])
        skill_dirs = [Path(d) for d in dirs] if dirs else [config.skills_dir()]
    else:
        skill_dirs = [Path(d) for d in skill_dirs]

    if on_progress:
        on_progress("read", skill_dirs)
    g = _gather(source_dir, skill_dirs, db_path)

    if on_progress:
        on_progress("write", None)
    record_md = _gen_record(g)
    dashboard_md = _gen_dashboard(g)
    record_path = source_dir / "RECORD.md"
    dashboard_path = source_dir / "DASHBOARD.md"
    record_path.write_text(record_md, encoding="utf-8")
    dashboard_path.write_text(dashboard_md, encoding="utf-8")

    # R1 调度器 MVP：刷全量已装能力索引 + CLAUDE.md sentinel 注入（锦上添花，不崩主流程）
    index_info = _write_installed_index(db_path, on_progress)

    result = {
        "source_video": source_dir.name,
        "verified_repo": g["full_name"],
        "record_path": str(record_path),
        "dashboard_path": str(dashboard_path),
        "integrity": {
            "disk_active_distinct": g["disk_distinct"],
            "registry_active": len(g["active"]),
            "orphans": g["orphans"],
            "missing": g["missing"],
            "ok": g["disk_distinct"] == len(g["active"]) and not g["orphans"] and not g["missing"],
        },
        "sessions": len(g["src_sessions"]),
        "this_run_installed": [d["name"] for d in g["new_installed"]],
    }
    if index_info:
        result["installed_index"] = index_info
    return result


# ---- 直接运行：python -m skillbrew.record <源目录> [--skills-dir DIR ...] ----
def _main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m skillbrew.record <源目录> [--skills-dir DIR ...]")
        print("     源目录需含 install_list.json + dedup.json（先跑 verify、dedup）")
        return 1
    src = Path(sys.argv[1])
    dirs: list[str] = []
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--skills-dir" and i + 1 < len(sys.argv):
            dirs.append(sys.argv[i + 1])
            i += 2
        else:
            i += 1
    print(f"[记录+看板] {src}")
    r = record(src, skill_dirs=[Path(d) for d in dirs] or None)
    ig = r["integrity"]
    print(f"[OK] 本次装 {len(r['this_run_installed'])} 个；本源会话 {r['sessions']} 次")
    print(f"     落盘核对：磁盘 {ig['disk_active_distinct']} == 台账 {ig['registry_active']}"
          f" → {'✅一致' if ig['ok'] else '⚠️不一致'}")
    print(f"     记录 → {r['record_path']}")
    print(f"     看板 → {r['dashboard_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
