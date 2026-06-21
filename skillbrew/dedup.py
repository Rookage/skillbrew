"""dedup：去重 —— 扫本地已装 skill + MCP 建基准，再逐项比 install_list（按 form 分发），判 new/merge/skip。

D18（章程 §4）：去重基准 = 实时扫本机已装 skill，每台机器/每个 Agent 不同。
全新机基准=0 → 全 new 直接加；成熟 Agent 已装很多 → 门槛高、逐项比对、
重叠的去芜存菁/整并、不重叠的登记。两条推论：① 分享文件的去重指令不可硬编码
比对目标；② skillbrew 去重模块须扫本地优先→再比台账。

三条比对层（从严到宽，命中即停）：
  ① 名字命中 → skip（已装 / 已整并）
     install_list 的 name 是仓库裸名（grill-me），本机/台账名常带分类前缀
     （productivity-grill-me）→ 归一化后用"后缀包含"判定（baseline 名更长、
     裸名是其后缀）。台账里 status=merged 的（如 tdd 已整并进 Python测试技能）
     也算 skip。
  ② 描述关键词重叠 → merge（建议人工确认整并，不自动决定）
     名字不像、但描述共享 ≥3 个有意义英文词（如 design/interface/module）→
     标"建议整并"留待 install 授权时由人定。取 3（非 2）求精、防泛词误并：
     skill/agent/file/issue/test 等在 skills 台账里几乎条条都有、无判别力，
     连同停用；阈值 2 会把不相关 skill（如 qa↔coze-file-send 共 [agent,file]）
     误判整并。仅同语种有效（英文↔英文）；跨语种语义整并（如英文 tdd ↔
     中文 Python测试技能）非纯标准库可判，需人工或后续 LLM 辅助 —— 本模块
     如实标注此局限，不硬猜。
  ③ 都不沾 → new（新装）

刹车：dedup 只判定 + 出报告 dedup.json，不改台账、不安装。台账在 install
（需 --approve 授权）时才动，保"你落盘就是什么"。
纯标准库（sqlite/re/json），不调 LLM、不耗配额、不要 key。

归一化 _key（与 verify._norm 的区别）：verify 只比英文 skill 名，_norm 去非
[a-z0-9] 无妨；dedup 基准含中文名 skill（GitHub工具 / GitHub趋势追踪），
若也去 CJK 会把两者都压成 "github" 而撞键 → 必须保留 CJK（仅去标点/分隔符）。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import registry
from .verify import parse_frontmatter  # 复用 SKILL.md frontmatter 轻量解析

SKILL_MD = "SKILL.md"
# 描述共享 ≥N 个有意义词才标 merge 候选。取 3（而非 2）求精：merge 是"建议人工确认"
# 的整并候选，宁少勿滥——2 个泛词重叠（如 [skill, agent]）多半是假阳性，留给人看
# 反成噪音；3 个有意义词重叠才值得一标。漏判的弱重叠只会落 new 多装一份，代价小。
_MERGE_MIN_SHARED = 3


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _key(s: str) -> str:
    """归一化 skill 名做去重主键：小写 + 去标点/分隔符，但保留 CJK 字母。

    productivity-grill-me → productivitygrillme；grill-me → grillme；
    GitHub工具 → github工具；GitHub趋势追踪 → github趋势追踪（两者不撞键）。
    """
    return re.sub(r"[\W_]+", "", s.lower(), flags=re.UNICODE)


# ---- 本地扫描：扫 .claude/skills/ 各子目录，解析 SKILL.md frontmatter ----

def scan_local_skills(skill_dirs: list[Path]) -> list[dict]:
    """扫一组 .claude/skills/ 目录，返回每个 skill 的基准信息。

    每个 skill = 一个含 SKILL.md 的子目录。返回 [{name, display_name,
    description, path, file_count, source}]。同一 skill 出现在多个目录
    （如 using-coze-cli 同时在工作区与用户级）会各出一条，由 build_baseline
    按规范名归并。
    """
    out: list[dict] = []
    for d in skill_dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for sub in sorted(d.iterdir()):
            if not sub.is_dir():
                continue
            sk = sub / SKILL_MD
            if not sk.exists():
                continue
            display_name, description = sub.name, ""
            try:
                fm = parse_frontmatter(sk.read_text(encoding="utf-8", errors="replace"))
                display_name = fm.get("name", sub.name)
                description = fm.get("description", "")
            except Exception:  # noqa: BLE001  frontmatter 解析失败不阻塞，退回用目录名
                pass
            file_count = sum(1 for p in sub.rglob("*") if p.is_file())
            out.append({
                "name": sub.name,
                "display_name": display_name,
                "description": description,
                "path": str(sub),
                "file_count": file_count,
                "source": "disk",
            })
    return out


# ---- 本地扫描：扫已注册 MCP 服务器（user/local/project scope）----

def _mcp_transport(cfg: dict) -> str:
    """从一条 MCP 配置推断传输方式：stdio（有 command）/ http / sse / unknown。

    ~/.claude.json 里 stdio 型写 {"command": "npx", "args": [...]}；
    远程型写 {"type": "http"|"sse", "url": "..."}。
    """
    if not isinstance(cfg, dict):
        return "unknown"
    if cfg.get("command"):
        return "stdio"
    t = str(cfg.get("type") or "").lower()
    if t in ("http", "sse"):
        return t
    url = str(cfg.get("url") or "")
    if url:
        return "sse" if "sse" in url.lower() else "http"
    return "unknown"


def scan_local_mcps(claude_json_path: Path | str | None = None,
                    project_mcp_path: Path | str | None = None,
                    cwd: str | None = None) -> list[dict]:
    """扫本机已注册 MCP 服务器建基准。直接读 JSON，不依赖 CLI 输出格式（人类文本解析脆）。

    - user scope：~/.claude.json 顶层 mcpServers
    - local scope：~/.claude.json projects[<cwd>].mcpServers
    - project scope：./.mcp.json 顶层 mcpServers
    返回 [{name, scope, transport}]，按 (name, scope) 去重。文件不存在/无 mcpServers → []。
    """
    from . import config  # 延迟导入，与 _now_iso 的 datetime 同风格
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

    cj_path = Path(claude_json_path) if claude_json_path else config.claude_json_path
    if cj_path.exists():
        try:
            data = json.loads(cj_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001  ~/.claude.json 损坏不阻塞去重，退回空基准
            data = {}
        for name, cfg in (data.get("mcpServers") or {}).items():  # user scope
            key = (name, "user")
            if key not in seen:
                seen.add(key)
                out.append({"name": name, "scope": "user", "transport": _mcp_transport(cfg)})
        cwd_key = cwd or str(Path.cwd())
        proj = (data.get("projects") or {}).get(cwd_key) or {}
        for name, cfg in (proj.get("mcpServers") or {}).items():  # local scope
            key = (name, "local")
            if key not in seen:
                seen.add(key)
                out.append({"name": name, "scope": "local", "transport": _mcp_transport(cfg)})

    pm_path = Path(project_mcp_path) if project_mcp_path else (Path.cwd() / ".mcp.json")
    if pm_path.exists():  # project scope
        try:
            pdata = json.loads(pm_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pdata = {}
        for name, cfg in (pdata.get("mcpServers") or {}).items():
            key = (name, "project")
            if key not in seen:
                seen.add(key)
                out.append({"name": name, "scope": "project", "transport": _mcp_transport(cfg)})
    return out


def load_registry_skills(db_path: Path | str | None = None) -> list[dict]:
    """从台账读全部 skill（active+merged）做基准。台账不存在（全新机）返回 []。"""
    db_path = Path(db_path) if db_path else registry.DB_PATH
    if not db_path.exists():
        return []
    conn = registry.connect(db_path)
    try:
        rows = registry.list_skills(conn)  # 全部状态
    finally:
        conn.close()
    return [{
        "name": r["name"],
        "display_name": r.get("display_name") or r["name"],
        "description": "",  # 台账无 description 列；merge 仅靠磁盘 skill 的描述
        "path": r.get("install_path") or "",
        "file_count": r.get("file_count") or 0,
        "source": "registry",
        "status": r.get("status", "active"),
        "merged_into": r.get("merged_into") or "",
        "category": r.get("category") or "",
    } for r in rows]


def _status_counts(entries: list[dict]) -> dict:
    out: dict[str, int] = {}
    for e in entries:
        out[e["status"]] = out.get(e["status"], 0) + 1
    return out


def build_baseline(skill_dirs: list[Path], db_path: Path | str | None = None) -> dict:
    """合并本地扫描 + 台账 + 已注册 MCP，按 _key 归并成基准。返回 {entries, counts, mcps, mcp_keys}。

    每个基准条目：{name, key, display_name, description, paths, sources,
    status, merged_into, category}。磁盘与台账同名 → 合一条（sources 含两者）；
    台账有但磁盘无（如 merged 的 tdd）→ 仍保留（status=merged）。
    MCP 基准 = 已注册服务器的归一化名集合（mcp_keys），与 skill 同 _key、形态无关：
    同名 Skill+MCP 视为同一能力（counts.distinct 取并集去重）。
    """
    disk = scan_local_skills(skill_dirs)
    reg = load_registry_skills(db_path)

    by_key: dict[str, dict] = {}
    for s in disk + reg:
        k = _key(s["name"])
        if not k:
            continue
        e = by_key.setdefault(k, {
            "name": s["name"], "key": k,
            "display_name": s.get("display_name", s["name"]),
            "description": s.get("description", ""), "paths": [], "sources": [],
            "status": "active", "merged_into": "", "category": s.get("category", ""),
        })
        if s.get("path"):
            e["paths"].append(s["path"])
        if s["source"] not in e["sources"]:
            e["sources"].append(s["source"])
        if s["source"] == "registry":  # 台账行带状态/分类信息
            if s.get("status"):
                e["status"] = s["status"]
            if s.get("merged_into"):
                e["merged_into"] = s["merged_into"]
            if s.get("category") and not e["category"]:
                e["category"] = s["category"]
        if s.get("description") and not e["description"]:  # 磁盘行带描述，优先取非空
            e["description"] = s["description"]
    entries = sorted(by_key.values(), key=lambda x: x["name"])
    mcps = scan_local_mcps()
    mcp_keys = {_key(m["name"]) for m in mcps if _key(m["name"])}
    counts = {
        "distinct": len(set(by_key.keys()) | mcp_keys),  # 能力去重：skill + mcp 同名算一个
        "disk_entries": len(disk),
        "registry_rows": len(reg),
        "mcp_registered": len(mcps),
        "by_status": _status_counts(entries),
    }
    return {"entries": entries, "counts": counts, "mcps": mcps, "mcp_keys": mcp_keys}


# ---- 描述关键词重叠（merge 候选）----

_STOP = {
    "the", "a", "an", "to", "for", "of", "in", "on", "and", "or", "when", "user",
    "wants", "use", "used", "is", "this", "that", "with", "into", "from", "your",
    "you", "it", "its", "as", "by", "be", "are", "was", "will", "can", "not", "but",
    "they", "their", "them", "which", "what", "about", "more", "than", "also", "then",
    "so", "if", "else", "up", "out", "off", "via", "any", "all", "new", "one", "two",
    "etc", "using", "want", "needs", "need", "mention", "mentions", "session",
    "current", "before", "after", "during", "while", "each", "both", "other", "another",
    "has", "have", "had", "been", "being", "does", "did", "how", "why", "who", "now",
    # 领域泛词（skills+AI 工具台账里几乎每条描述都带，对"是否同一 skill"无判别力）：
    # 不加会把不相关的 skill 误判整并（实测：qa↔coze-file-send 共 [agent,file]、
    # ask-matt↔writing-great-skills 共 [skill,skills] 等假阳性）。真正的同名测试/技能
    # 重复由①名字命中层兜住（如 tdd 已 skip 进 Python测试技能），不靠这层泛词。
    "skill", "skills", "agent", "claude", "code", "file", "files",
    "issue", "issues", "test", "tests",
}


def _keywords(text: str) -> set[str]:
    """从描述里抽有意义英文小写词（len>=3，去停用词）。中文不参与跨语种比对。"""
    return {w for w in re.findall(r"[a-z]{3,}", text.lower()) if w not in _STOP}


# ---- 逐项判定 ----

def classify(install_list: dict, baseline: dict) -> list[dict]:
    """对 install_list 每个 item 判 new/merge/skip（按 form 分发）。返回判定列表。

    items 为规范键，skills 为兼容别名（同数组引用）；旧 artifact 只有 skills。
    按 item["form"] 分发：MCP → 查本地已注册同名服务器（mcp_keys），未注册即 new，
    已注册即 skip（MCP 无整并语义，不产 merge）；Skill → 现有三层（名字命中 /
    关键词重叠 / 新装）。每条 decision 带 form。
    """
    entries = baseline["entries"]
    mcp_keys = baseline.get("mcp_keys", set())
    # 预算每个基准条目的关键词集（仅磁盘带描述的才有）
    base_kw: list[tuple[dict, set[str]]] = [
        (e, _keywords(e["display_name"] + " " + e["description"])) for e in entries
    ]

    items = install_list.get("items") or install_list.get("skills", [])

    decisions: list[dict] = []
    for s in items:
        raw_form = s.get("form") or "Skill"
        form = "MCP" if str(raw_form).strip().upper() == "MCP" else "Skill"
        cand_name = s["name"]
        ck = _key(cand_name)
        category = s.get("category", "")

        if form == "MCP":
            # MCP 判据：本地已注册同名服务器（_key 形态无关）→ skip，否则 new
            if ck and ck in mcp_keys:
                decisions.append({
                    "name": cand_name, "form": "MCP", "category": category,
                    "decision": "skip",
                    "reason": f"已注册：MCP {cand_name}",
                    "target": cand_name,
                })
            else:
                decisions.append({
                    "name": cand_name, "form": "MCP", "category": category,
                    "decision": "new", "reason": "本地未注册该 MCP",
                })
            continue

        # ---- Skill 判据（现有三层层级，每条带 form="Skill"）----
        cand_kw = _keywords((s.get("display_name") or "") + " " + (s.get("description") or ""))

        # ① 名字命中：精确 或 baseline 名以裸名为后缀（分类前缀变体）
        hit = None
        for e in entries:
            ek = e["key"]
            if not ek or len(ck) < 3:
                continue
            if ek == ck or ek.endswith(ck):
                hit = e
                break

        if hit:
            if hit["status"] == "merged":
                decisions.append({
                    "name": cand_name, "form": "Skill", "category": category,
                    "decision": "skip",
                    "reason": f"已整并进 {hit['merged_into'] or hit['name']}",
                    "target": hit["merged_into"] or hit["name"],
                })
            elif hit["name"] == cand_name:
                decisions.append({
                    "name": cand_name, "form": "Skill", "category": category,
                    "decision": "skip",
                    "reason": f"已装：{hit['name']}",
                    "target": hit["name"],
                })
            else:
                decisions.append({
                    "name": cand_name, "form": "Skill", "category": category,
                    "decision": "skip",
                    "reason": f"已装：{hit['name']}（裸名 {cand_name} 的分类前缀变体）",
                    "target": hit["name"],
                })
            continue

        # ② 描述关键词重叠 → merge 候选（取重叠最多的，建议人工确认）
        best, best_shared = None, set()
        for e, kw in base_kw:
            if not kw or not cand_kw:
                continue
            shared = cand_kw & kw
            if len(shared) >= _MERGE_MIN_SHARED and len(shared) > len(best_shared):
                best, best_shared = e, shared
        if best:
            decisions.append({
                "name": cand_name, "form": "Skill", "category": category,
                "decision": "merge",
                "reason": f"描述重叠 {sorted(best_shared)}，建议整并进 {best['name']}（需人工确认）",
                "target": best["name"],
                "shared": sorted(best_shared),
            })
            continue

        # ③ 新装
        decisions.append({
            "name": cand_name, "form": "Skill", "category": category,
            "decision": "new", "reason": "无匹配，新装",
        })
    return decisions


def dedup(source_dir: Path, *, skill_dirs: list[Path] | None = None,
          db_path: Path | str | None = None, on_progress=None) -> dict:
    """对一个源目录跑去重：读 install_list.json → 建基准 → 逐项判定 → 写 dedup.json。

    返回报告 dict（含 dedup_path）。dedup 纯本地（磁盘+台账），不调 LLM、不安装。
    skill_dirs 默认 [~/.claude/skills]；CLI 会把工作区目录一起传进来。
    """
    source_dir = Path(source_dir)
    il_path = source_dir / "install_list.json"
    if not il_path.exists():
        raise RuntimeError(f"没有 install_list.json，先跑 verify：{il_path}")
    install_list = json.loads(il_path.read_text(encoding="utf-8"))

    if skill_dirs is None:
        skill_dirs = [Path.home() / ".claude" / "skills"]
    skill_dirs = [Path(d) for d in skill_dirs]

    if on_progress:
        on_progress("scan", skill_dirs)
    baseline = build_baseline(skill_dirs, db_path)

    items = install_list.get("items") or install_list.get("skills", [])
    if on_progress:
        on_progress("classify", len(items))
    decisions = classify(install_list, baseline)

    summary = {"new": 0, "merge": 0, "skip": 0, "total": len(decisions)}
    for d in decisions:
        summary[d["decision"]] += 1

    # 形态分布（verify 已写 form；旧 Skill artifact 无 form 字段时全归 Skill）
    by_form: dict[str, int] = {}
    for d in decisions:
        f = d.get("form", "Skill")
        by_form[f] = by_form.get(f, 0) + 1

    report = {
        "source_video": install_list.get("source_video", source_dir.name),
        "install_list_repo": install_list.get("verified_repo", {}).get("full_name", ""),
        "install_list_form": install_list.get("form", ""),
        "baseline": {
            "scanned_at": _now_iso(),
            "skill_dirs": [str(d) for d in skill_dirs],
            "db_path": str(db_path or registry.DB_PATH),
            "counts": baseline["counts"],
        },
        "decisions": decisions,
        "summary": summary,
        "by_form": by_form,
        "unresolved": install_list.get("unresolved", []),
        "note": (
            "merge = 建议人工确认的整并候选（同语种描述重叠≥3 个有意义词，"
            "已剔 skill/agent/file/issue/test 等泛词）；跨语种语义整并"
            "（如英文 tdd ↔ 中文 Python测试技能）非纯标准库可判，需人工或后续 LLM 辅助。"
            "dedup 只判定 + 出报告，不改台账、不安装；安装需另跑 install 并单独授权（--approve）。"
        ),
        "generated_at": _now_iso(),
    }
    out_path = source_dir / "dedup.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**report, "dedup_path": str(out_path)}


# ---- 直接运行：python -m skillbrew.dedup <源目录> [--skills-dir DIR ...] ----
def _main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m skillbrew.dedup <源目录> [--skills-dir DIR ...]")
        print("     源目录需含 install_list.json（先跑 verify）")
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
    print(f"[去重] {src}")
    r = dedup(src, skill_dirs=[Path(d) for d in dirs] or None)
    bc = r["baseline"]["counts"]
    print(f"[OK] 基准 {bc['distinct']} 个 distinct（磁盘 {bc['disk_entries']} + 台账 {bc['registry_rows']} + 已注册 MCP {bc['mcp_registered']}）")
    forms = " ".join(f"{k}={v}" for k, v in r["by_form"].items()) or "—"
    print(f"     new={r['summary']['new']}  merge={r['summary']['merge']}  skip={r['summary']['skip']}  [{forms}]")
    if r.get("unresolved"):
        print(f"     unresolved={len(r['unresolved'])}（catalog miss，透传交用户定夺）")
    print(f"     报告 → {r['dedup_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
