"""recommend：判断步 —— 去重之后、安装之前，先判「值不值得装」。

D19（章程 §4 判断先行·协助人类判断）：用户盲目丢素材 → skillbrew 先消化 + 判断
→ 主动给「值得装 / 不值得装 / 挑着装 / 整源跳过」建议 → 人定。dedup 只判「是否
重复」（new/merge/skip），**不判「是否值得装」**；本模块补这一层。两者分开（dedup
的 new 不等于值得装：可能是未完成 / 个人用 / 与已有重叠 / 整源是配置商店而非技能集）。

D20（安装粒度·挑着买）：配置商店源（如 davila7/claude-code-templates）禁整目录盲拷；
支持单组件 / 购物车 / npx 选装。本模块产出 approved 名单，install 据此只装被认可的。

D21（模型前置·文本必备·视觉可选优雅降级）：判断步三模式可切——
  - keyword：无 key、不烧 token，纯规则打分（默认安全模式）；
  - manual ：无 key、不烧 token，列清单人工勾选（无 key 不走死路，恒可用）；
  - ai     ：调文本模型判断（烧 token，需用户在场；模型可热插拔，D15）。
视觉模型与本步无关（判断只吃文本：候选名/描述/分类 + 本机画像）。

D22（反盲盒·透明可追）：报告须说清每个候选「是什么 / 值不值得 / 为什么」（调用方式
「@名/触发提示词」由 record 看板的 D22 段补；本模块至少给「为什么」+ verdict）。

【乐高拆法】本模块分独立小节，坏哪修哪、互不牵连（用户 2026-06-20 拍板的工作方式）：
  积木 A（本节）：纯核心 —— 数据模型 + 汇总 + 报告装配。无 IO、无 LLM、最易测。
  积木 E：本机能力画像 build_profile（复用 dedup.build_baseline，D18 动态基准）。
  积木 B：keyword 模式打分 score_keyword（纯规则，不烧 token）。
  积木 C：manual 模式人工勾选 pick_manual（stdin 交互，不烧 token）。
  积木 D：ai 模式 LLM 判断 judge_ai（烧 token，用户在场，最后实现）。
  积木 F：doctor 自检 recommend_health（文本必备/视觉可选/三模式可用性，呼应 D21）。
  CLI 接线 + 看板（cmd_recommend + 看板新状态 + finding-2 修复）在 cli.py / record.py。

刹车：recommend 只判断 + 出 recommend.json，不改台账、不安装。安装需另跑 install
并单独授权（--approve），且 install 只装本模块 approved 的子集（D20）。
纯标准库（dataclasses/datetime/typing），keyword/manual 模式不调 LLM、不耗配额、不要 key。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# ---- 常量 ----

# 判断步三模式（D21）
MODE_KEYWORD = "keyword"  # 无 key、不烧 token：规则打分
MODE_MANUAL = "manual"  # 无 key、不烧 token：人工勾选
MODE_AI = "ai"  # 烧 token：文本模型判断（用户在场）
MODES = (MODE_KEYWORD, MODE_MANUAL, MODE_AI)

# 候选级判定（每条 new/merge/skip 的 verdict）
V_WORTH = "值得装"  # 值得安装
V_NOT_WORTH = "不值得装"  # 不值得安装
V_INSTALLED = "已装"  # dedup 判 skip（已装/已整并），无需再判值不值得
V_MERGE = "建议整并"  # dedup 判 merge，须人工确认整并（不自动装也不自动否）
CANDIDATE_VERDICTS = (V_WORTH, V_NOT_WORTH, V_INSTALLED, V_MERGE)

# 源级汇总（D19 四桶 + 无需新装边角）
SV_ALL_WORTH = "值得装"  # 所有 new 都值得 → 整源可装
SV_PICK = "挑着装"  # new 有值得有不值得 → 挑着买（D20）
SV_ALL_SKIP = "不值得装"  # 所有 new 都不值得
SV_SOURCE_SKIP = "整源跳过"  # 源级信号否决（如配置商店非技能集，davila7 案例）
SV_NOTHING_NEW = "无需新装"  # 没有 new 候选（全 skip/merge）
SOURCE_VERDICTS = (SV_ALL_WORTH, SV_PICK, SV_ALL_SKIP, SV_SOURCE_SKIP, SV_NOTHING_NEW)


def _now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


# ---- 积木 A：纯核心（数据模型 + 汇总 + 装配）------------------------------------


@dataclass
class Profile:
    """本机能力画像（积木 E 产出，喂给 B/D 打分判断）。D18：动态基准，不硬编码。

    各字段由 build_profile（积木 E）从 dedup.build_baseline 实时扫描填充；本核心只读
    不造，故 Profile 在此仅定契约（E 实现时填充）。
    """

    distinct: int = 0  # 本机 distinct 能力数
    by_category: dict[str, int] = field(default_factory=dict)  # 分类计数（仅 active，可用能力分布）
    names: set[str] = field(default_factory=set)  # 已有能力名集合（归一化 key，含 merged 防重复推）
    keywords: set[str] = field(default_factory=set)  # 已有能力描述关键词集合
    source: str = "disk+registry"  # 画像来源标记


@dataclass
class Judgment:
    """单条候选的判断结果。"""

    name: str  # 候选名（install_list 裸名）
    decision: str  # dedup 判定：new / merge / skip
    verdict: str  # 候选级 verdict（CANDIDATE_VERDICTS 之一）
    reason: str  # 为什么这个 verdict（透明可追，D22）
    score: float | None = None  # keyword 打分（0~1，越高越值得）；他模 None
    signals: list[str] = field(default_factory=list)  # 命中的判分信号（透明可追）
    target: str = ""  # merge/skip 的目标能力名
    mode: str = ""  # 由哪个模式产出（keyword/manual/ai/trivial）
    form: str = (
        "Skill"  # 产物形态（Skill/MCP/...）；形态无关判值不值得，仅供 install/record 分发与展示
    )
    usability: str = "ready"  # 装完即可用度（ready/needs_credentials/needs_runtime/needs_config，D22 反黑箱透明标注）


def judge_trivial(decision: dict) -> Judgment | None:
    """对 dedup 的 skip/merge 候选出「无需打分」的判断；new 返回 None（须 B/D 打分）。

    skip → 已装（已装或已整并，不用再判值不值得）；
    merge → 建议整并（须人工确认，不自动装也不自动否）；
    new  → None（值不值得须靠 keyword/ai 打分，或 manual 人工选）。
    """
    d = decision.get("decision", "")
    name = decision.get("name", "")
    form = decision.get("form", "Skill")
    if d == "skip":
        return Judgment(
            name=name,
            decision=d,
            verdict=V_INSTALLED,
            reason=decision.get("reason", "已装/已整并"),
            target=decision.get("target", ""),
            mode="trivial",
            form=form,
        )
    if d == "merge":
        return Judgment(
            name=name,
            decision=d,
            verdict=V_MERGE,
            reason=decision.get("reason", "描述重叠，建议人工确认整并"),
            target=decision.get("target", ""),
            mode="trivial",
            form=form,
        )
    return None  # new：留给 B/D/C


def merge_judgments(
    decisions: list[dict],
    new_judgments: list[Judgment],
) -> list[Judgment]:
    """合并：new 候选用 B/D/C 产出的判断，skip/merge 用 judge_trivial 兜底。

    保证每个 decision 都有一条 Judgment（report 完整、install 可全量对账）。
    new 候选若没拿到判断（B/D 漏了），降级标「不值得装」并标 reason，防静默漏判。
    """
    by_name: dict[str, Judgment] = {j.name: j for j in new_judgments}
    out: list[Judgment] = []
    for dec in decisions:
        name = dec.get("name", "")
        if dec.get("decision") == "new":
            j = by_name.get(name)
            if j is None:
                j = Judgment(
                    name=name,
                    decision="new",
                    verdict=V_NOT_WORTH,
                    reason="未拿到打分判断，默认不装（防静默漏判）",
                    mode="(missing)",
                    form=dec.get("form", "Skill"),
                )
            out.append(j)
        else:
            tj = judge_trivial(dec)
            if tj is not None:
                out.append(tj)
    return out


def approved_names(judgments: list[Judgment]) -> list[str]:
    """install 该装的子集（D20 挑着买）：verdict=值得装 的候选名，保序。

    建议整并（merge）须人工另确认，不计入自动 approved；已装/不值得装跳过。
    """
    return [j.name for j in judgments if j.verdict == V_WORTH]


def approved_items(judgments: list[Judgment], install_list: dict) -> list[dict]:
    """install 直接消费的 approved 子集（D20 挑着买）：verdict=值得装 的候选，
    按 install_list.items 名反查完整安装条目（form/mcp/install_method/usability 等）。

    Judgment 只带 name/verdict/form/usability，不带 mcp/install_method —— 故需 install_list
    反查补全。install 拿到即可按 item["form"] 分发（Skill 整目录拷 / MCP 注册）。
    skills[] 兼容旧 artifact（与 items[] 同数组引用）。approved_names() 保留向后兼容。
    """
    items = install_list.get("items") or install_list.get("skills", [])
    by_name = {it.get("name", ""): it for it in items if it.get("name")}
    out: list[dict] = []
    for j in judgments:
        if j.verdict != V_WORTH:
            continue
        item = by_name.get(j.name)
        if item is None:
            # approved 但 install_list 无对应条目（不应发生）：退回 Judgment 字段保条目不丢
            item = {"name": j.name, "form": j.form, "usability": j.usability}
        out.append(item)
    return out


def build_descriptions(install_list: dict) -> dict[str, str]:
    """形态无关地构造 name→描述，喂给 keyword/manual/ai 打分判断（积木 B/C/D 用）。

    Skill 项用 description；MCP 项无 description 字段，用 capability_name + invoke_hint
    拼装形态无关描述。旧 artifact 只有 skills[] 也兼容。

    修隐藏 bug：CLI 原从 install_list["skills"][].get("description") 取描述，MCP 项
    无 description → 空串 → score_keyword 扣 0.2（无描述）误判不值得装。本函数按形态
    取对等描述，保证 MCP 候选不被「无描述」误杀。
    """
    items = install_list.get("items") or install_list.get("skills", [])
    out: dict[str, str] = {}
    for it in items:
        name = it.get("name", "")
        if not name:
            continue
        desc = (it.get("description") or "").strip()
        if not desc:
            # MCP 项无 description：用 capability_name + invoke_hint 拼装形态无关描述
            parts = [it.get("capability_name", ""), it.get("invoke_hint", "")]
            desc = " ".join(p for p in parts if p).strip()
        out[name] = desc
    return out


def build_usability(install_list: dict) -> dict[str, str]:
    """构造 name→usability 供 Judgment 标注（D22 反黑箱透明标注）。

    install_list 的 items 带 usability（ready/needs_credentials/needs_runtime/
    needs_config），但 dedup decisions 不带（dedup 只判重复、不带安装画像）。故从
    install_list 取 usability 透传给打分判断，避免 MCP 候选一律误标 ready（如 github
    需凭证、playwright 需运行时却被当 ready）。
    """
    items = install_list.get("items") or install_list.get("skills", [])
    return {it.get("name", ""): it.get("usability", "ready") for it in items if it.get("name")}


def rollup_source_verdict(
    judgments: list[Judgment],
    *,
    source_skip_reason: str = "",
) -> str:
    """把候选级 verdict 汇总成源级建议（D19 四桶）。

    source_skip_reason 非空 → 整源跳过（源级信号否决，如检测到配置商店非技能集）。
    否则按 new 候选的值得/不值得分布：全值得→值得装、全不值得→不值得装、
    混合→挑着装、无 new→无需新装。
    """
    if source_skip_reason:
        return SV_SOURCE_SKIP
    news = [j for j in judgments if j.decision == "new"]
    if not news:
        return SV_NOTHING_NEW
    worth = sum(1 for j in news if j.verdict == V_WORTH)
    if worth == len(news):
        return SV_ALL_WORTH
    if worth == 0:
        return SV_ALL_SKIP
    return SV_PICK


def _verdict_counts(judgments: list[Judgment]) -> dict[str, int]:
    out: dict[str, int] = {}
    for j in judgments:
        out[j.verdict] = out.get(j.verdict, 0) + 1
    return out


def assemble_report(
    decisions: list[dict],
    judgments: list[Judgment],
    *,
    mode: str,
    source_video: str = "",
    repo: str = "",
    source_skip_reason: str = "",
    note: str = "",
) -> dict:
    """装配 recommend.json（写盘结构）。纯函数：只组装，不 IO、不写盘。

    decisions：dedup.json 的 decisions（仅取数 source_video/repo 等元信息，候选明细
    已折进 judgments，不重复塞回 report，免冗余）。
    judgments：merge_judgments 产出的全量判断（每个 decision 一条）。
    """
    sv = rollup_source_verdict(judgments, source_skip_reason=source_skip_reason)
    # 整源跳过（source_skip_reason 非空）→ approved 必须置空：install 什么都不该装，
    # 与 source_verdict=整源跳过 语义一致，否则 report 自相矛盾（D19/D20）。
    approved = [] if source_skip_reason else approved_names(judgments)
    report: dict[str, Any] = {
        "source_video": source_video,
        "install_list_repo": repo,
        "mode": mode,
        "source_verdict": sv,
        "source_skip_reason": source_skip_reason,
        "judgments": [asdict(j) for j in judgments],
        "summary": {
            "total": len(judgments),
            "by_verdict": _verdict_counts(judgments),
            "approved": len(approved),
        },
        "approved": approved,
        "note": note or _DEFAULT_NOTE,
        "generated_at": _now_iso(),
    }
    return report


_DEFAULT_NOTE = (
    "判断步（recommend）：dedup 只判「是否重复」，本步补判「是否值得装」（D19）。"
    "verdict=值得装 的计入 approved，install 只装 approved 子集（D20 挑着买）。"
    "建议整并（merge）须人工另确认；已装/不值得装跳过。"
    "mode=keyword/manual 不烧 token；ai 烧 token（D21）。"
)


# ---- 积木 E：本机能力画像 build_profile -----------------------------------------


def build_profile(
    skill_dirs: list[Path],
    db_path: Path | str | None = None,
) -> Profile:
    """本机能力画像：复用 dedup.build_baseline 扫磁盘+台账，聚合成 Profile（D18 动态基准）。

    喂给 keyword/ai 模式打分判断用。纯本地（磁盘+台账），不调 LLM、不烧 token、不要 key。
    复用 dedup 的 build_baseline + _keywords，不另造扫描口径（与去重基准同源，DRY）。

    - by_category：仅计 active（可用能力分布；merged 已并入 target，不计免重复）；
    - names：计所有归一化 key（含 merged，防把已整并的当新候选推荐）；
    - keywords：计所有描述关键词（本机已覆盖的概念面，供候选重叠度打分）。
    """
    from . import dedup  # 延迟 import：dedup 不 import recommend，无循环；延迟更稳

    baseline = dedup.build_baseline(skill_dirs, db_path)
    entries = baseline["entries"]
    counts = baseline["counts"]

    by_category: dict[str, int] = {}
    names: set[str] = set()
    keywords: set[str] = set()
    for e in entries:
        if e.get("status") == "active":
            cat = e.get("category") or "(未分类)"
            by_category[cat] = by_category.get(cat, 0) + 1
        if e.get("key"):
            names.add(e["key"])
        kw = dedup._keywords((e.get("display_name") or "") + " " + (e.get("description") or ""))
        keywords |= kw

    return Profile(
        distinct=counts["distinct"],
        by_category=by_category,
        names=names,
        keywords=keywords,
        source="disk+registry",
    )


# ---- 积木 B：keyword 打分 score_keyword -----------------------------------------

# category → 倾向（DASHBOARD §6 同理：未完成/个人用不该装）
_CAT_PENALTY = ("in-progress", "personal", "deprecated")  # 扣分
_CAT_BONUS = ("engineering", "productivity", "misc", "pre-existing")  # 微加分
_SCORE_THRESHOLD = 0.5  # ≥值得装，<不值得装


def score_keyword(
    candidate: dict,
    profile: Profile,
    *,
    description: str = "",
    usability: str = "ready",
) -> Judgment:
    """keyword 模式：纯规则给单条 new 候选打分（0~1），不烧 token、不要 key。

    信号（D22 透明可追，每个命中记进 signals）：
      ① category：in-progress/personal/deprecated 扣分（未完成/个人用/废弃）；
         engineering/productivity/misc/pre-existing 微加分（实用类）。
      ② 描述质量：空/极短(<10 字) 扣分（信息不足无法判价值）。
      ③ 重叠饱和：候选名与本机 names 子串重叠，或描述关键词与 profile.keywords
         重叠≥3 → 扣分（近似已有；dedup 的 merge 是≥3 词强重叠已另判，这里补弱信号）。
    阈值 0.5：≥值得装，<不值得装。缺信息走中性（0.5）不误杀。
    """
    from . import dedup  # 复用 _key / _keywords，口径与去重一致

    name = candidate.get("name", "")
    category = (candidate.get("category") or "").strip()
    desc = (description or candidate.get("description") or "").strip()

    score = 0.5
    signals: list[str] = []

    # ① category
    if category in _CAT_PENALTY:
        score -= 0.3
        signals.append(f"分类={category}（未完成/个人用/废弃，倾向不装）")
    elif category in _CAT_BONUS:
        score += 0.1
        signals.append(f"分类={category}（实用类，微加分）")

    # ② 描述质量
    if not desc:
        score -= 0.2
        signals.append("无描述（信息不足，无法判价值）")
    elif len(desc) < 10:
        score -= 0.1
        signals.append(f"描述过短({len(desc)}字)")

    # ③ 重叠饱和
    key = dedup._key(name)
    if key:
        name_overlap = any(key in n or n in key for n in profile.names if n and n != key)
        if name_overlap:
            score -= 0.15
            signals.append("名与本机已有能力子串重叠")
    cand_kw = dedup._keywords(name + " " + desc)
    shared_kw = cand_kw & profile.keywords
    if len(shared_kw) >= 3:
        score -= 0.15
        signals.append(f"描述关键词与本机重叠{len(shared_kw)}个（概念已覆盖）")

    score = max(0.0, min(1.0, score))
    verdict = V_WORTH if score >= _SCORE_THRESHOLD else V_NOT_WORTH
    reason = "；".join(signals) if signals else "无显著正负信号，中性"
    return Judgment(
        name=name,
        decision="new",
        verdict=verdict,
        reason=reason,
        score=round(score, 2),
        signals=signals,
        mode="keyword",
        form=candidate.get("form", "Skill"),
        usability=usability or "ready",
    )


def score_keyword_batch(
    candidates: list[dict],
    profile: Profile,
    *,
    descriptions: dict[str, str] | None = None,
    usability: dict[str, str] | None = None,
) -> list[Judgment]:
    """对一批 new 候选逐条 keyword 打分。

    descriptions：name→描述（由 CLI 从 install_list.json 读好传入，纯函数不读盘）。
    usability：name→usability（D22 透明标注，同样从 install_list 读好传入）。dedup
    decisions 不带 usability，须由 CLI 从 install_list.items 透传，否则 MCP 候选
    一律误标 ready（如 github 需凭证被当 ready）。
    非 new 候选跳过（由 merge_judgments 用 judge_trivial 兜底）。
    """
    descriptions = descriptions or {}
    usability = usability or {}
    return [
        score_keyword(
            c,
            profile,
            description=descriptions.get(c.get("name", ""), ""),
            usability=usability.get(c.get("name", ""), "ready"),
        )
        for c in candidates
        if c.get("decision") == "new"
    ]


# ---- 积木 C：manual 人工勾选 pick_manual ----------------------------------------


def _format_menu(candidates: list[dict], descriptions: dict[str, str]) -> str:
    lines: list[str] = []
    for i, c in enumerate(candidates, 1):
        name = c.get("name", "")
        cat = c.get("category", "") or "-"
        desc = (descriptions.get(name, "") or c.get("description", "") or "").strip()
        if len(desc) > 60:
            desc = desc[:57] + "..."
        lines.append(f"  {i:>3}. {name}  [{cat}]  {desc}")
    return "\n".join(lines)


def pick_manual(
    candidates: list[dict],
    *,
    descriptions: dict[str, str] | None = None,
    usability: dict[str, str] | None = None,
    input_fn=input,
    print_fn=print,
) -> list[Judgment]:
    """manual 模式：列 new 候选清单人工勾选（D20 挑着买 / D22 反盲盒，不烧 token）。

    交互：打印编号清单 → 用户输「编号,编号」选装；a=全装；n 或回车=全不装；q=退出。
    选中→值得装，未选→不值得装。
    usability：name→usability（从 install_list 透传；dedup decisions 不带 usability）。
    input_fn/print_fn 可注入便于测（默认 input/print；非交互环境须注入 mock，否则卡 stdin）。
    """
    descriptions = descriptions or {}
    usability = usability or {}
    news = [c for c in candidates if c.get("decision") == "new"]
    if not news:
        return []
    print_fn("【manual 挑着买】以下 new 候选——输编号(逗号分隔)选装；a=全装；n/回车=全不装；q=退出")
    print_fn(_format_menu(news, descriptions))
    raw = input_fn("> ").strip().lower()

    chosen: set[int] = set()
    if raw == "a":
        chosen = set(range(len(news)))
    elif raw in ("", "n"):
        chosen = set()
    elif raw == "q":
        print_fn("已退出，本批均不装。")
        chosen = set()
    else:
        for tok in raw.replace(";", ",").split(","):
            tok = tok.strip()
            if tok.isdigit():
                idx = int(tok) - 1
                if 0 <= idx < len(news):
                    chosen.add(idx)

    judgments: list[Judgment] = []
    for idx, c in enumerate(news):
        name = c.get("name", "")
        u = usability.get(name, "ready")
        if idx in chosen:
            judgments.append(
                Judgment(
                    name=name,
                    decision="new",
                    verdict=V_WORTH,
                    reason="人工勾选安装",
                    mode="manual",
                    form=c.get("form", "Skill"),
                    usability=u,
                )
            )
        else:
            judgments.append(
                Judgment(
                    name=name,
                    decision="new",
                    verdict=V_NOT_WORTH,
                    reason="人工未勾选",
                    mode="manual",
                    form=c.get("form", "Skill"),
                    usability=u,
                )
            )
    return judgments


# ---- 积木 D：ai LLM 判断 judge_ai（烧 token，用户在场，最后实现）------------------

_AI_SYSTEM = (
    "你是 skillbrew 判断步的判断助手。输入是「本机已装能力画像」+「一批候选 skill」。"
    "你的任务：判断每个候选是否值得安装到本机。判断依据：与已有能力是否重复、描述是否充分、"
    "是否实用完整（未完成 / 个人用 / 废弃倾向不值得）。要求：①只依据给出的信息，不编造候选内容；"
    "②**只输出一个 JSON 数组，不要任何解释、不要 markdown 代码围栏**。"
)

_AI_SCHEMA_HINT = """\
按此结构输出 JSON 数组（每条候选一个对象，字段名固定，值用中文）：
[
  {"name": "候选名（须与输入完全一致）", "verdict": "值得装" 或 "不值得装", "reason": "一句话理由"}
]
每条候选都必须出现，顺序不限，但 name 必须与输入完全一致。"""

# ai 批大小（每次 LLM 调用判多少候选）：太小=调用多费时费 token，太大=JSON 易乱难解析。10 折中。
_AI_BATCH_SIZE = 10


def _ai_profile_text(profile: Profile) -> str:
    """把本机画像压成喂模型的文本（控 token：名/关键词各取前若干）。"""
    names = sorted(profile.names)[:30]
    kws = sorted(profile.keywords)[:40]
    return (
        f"distinct 能力数：{profile.distinct}\n"
        f"分类分布：{profile.by_category}\n"
        f"已有能力名（部分）：{', '.join(names) if names else '(无)'}\n"
        f"已有能力关键词（部分）：{', '.join(kws) if kws else '(无)'}"
    )


def _ai_candidates_text(batch: list[dict], descriptions: dict[str, str]) -> str:
    lines: list[str] = []
    for i, c in enumerate(batch, 1):
        name = c.get("name", "")
        cat = c.get("category", "") or "-"
        desc = (descriptions.get(name, "") or c.get("description", "") or "").strip()
        if len(desc) > 120:
            desc = desc[:117] + "..."
        lines.append(f"{i}. {name} [{cat}] {desc}")
    return "\n".join(lines)


def _ai_build_prompt(batch: list[dict], profile: Profile, descriptions: dict[str, str]) -> str:
    return (
        f"=== 本机已装能力画像 ===\n{_ai_profile_text(profile)}\n\n"
        f"=== 待判断候选（共 {len(batch)} 条） ===\n{_ai_candidates_text(batch, descriptions)}\n\n"
        f"=== 输出要求 ===\n{_AI_SCHEMA_HINT}\n"
    )


def _extract_json_array(text: str) -> list:
    """从模型回复抠 JSON 数组：去围栏；数组直取；对象包数组（如 {"results":[...]}）则取其 list 值。

    对齐 plan._extract_json 的容错策略（去 ```json 围栏 + 平衡括号兜底），但目标是数组。
    """
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    parsed = None
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        pass
    if parsed is None:
        # 退而求其次：找第一个平衡的 [ ... ] 块
        start = s.find("[")
        if start < 0:
            raise ValueError(f"回复里找不到 JSON 数组:\n{text[:500]}")
        depth = 0
        for i in range(start, len(s)):
            if s[i] == "[":
                depth += 1
            elif s[i] == "]":
                depth -= 1
                if depth == 0:
                    parsed = json.loads(s[start : i + 1])
                    break
        if parsed is None:
            raise ValueError(f"JSON 数组方括号不平衡:\n{text[:500]}")
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        # 模型可能包了一层 {"results":[...]} / {"judgments":[...]}
        lists = [v for v in parsed.values() if isinstance(v, list)]
        if lists:
            return lists[0]
    raise ValueError(f"解析到的不是数组:\n{text[:500]}")


def _map_verdict(s: str) -> str:
    """模型返回的 verdict 文本 → 常量。先判「不值得」（「值得」是其子串易误中）。默认不装。"""
    t = (s or "").strip()
    if "不值得" in t:
        return V_NOT_WORTH
    if "值得" in t:
        return V_WORTH
    return V_NOT_WORTH


def judge_ai(
    candidates: list[dict],
    profile: Profile,
    *,
    descriptions: dict[str, str] | None = None,
    usability: dict[str, str] | None = None,
    cfg=None,
    chat_fn=None,
    batch_size: int = _AI_BATCH_SIZE,
    limit: int | None = None,
    on_batch=None,
    timeout: float = 120.0,
) -> list[Judgment]:
    """ai 模式：调文本模型给 new 候选判「值不值得装」（D21 热插拔，烧 token，用户在场）。

    分批喂模型（默认 10 条/批）：每批一次 chat_text → 解析 JSON 数组 → 逐条映射成 Judgment。
    候选名/描述/分类 + 本机画像一起喂，让模型知「已有什么」避免推荐重复（与 keyword 同思路）。

    - cfg：Config（用 cfg.text 文本模型；D21 任意品牌文本模型皆可，不写死 DeepSeek）。
    - chat_fn：可注入便于测（默认 llm.chat_text，签名 (cfg, prompt, system=, temperature=, timeout=)）；
      测试注入 mock 即不烧 token、不要 key。
    - usability：name→usability（从 install_list 透传；dedup decisions 不带 usability）。
    - limit：只判前 N 条 new（成本控制，None=全部）。未判到的 new 由 merge_judgments 兜底「不值得装」。
    - on_batch：进度回调 (i, n_batches, batch_size, ok) 供 CLI 打印（D22 透明 + 用户在场可监控）。
    - 单批调用/解析失败 → 整批降级「不值得装」+ reason（防静默漏判，与 merge_judgments 同口径），
      绝不让单批错拖垮整次判断。
    """
    descriptions = descriptions or {}
    usability = usability or {}
    news = [c for c in candidates if c.get("decision") == "new"]
    if limit is not None:
        news = news[:limit]
    if not news:
        return []

    if chat_fn is None:
        from . import llm

        chat_fn = llm.chat_text
    if cfg is None:
        raise RuntimeError("ai 模式需 cfg（文本模型配置），D21 前置")

    judgments: list[Judgment] = []
    batches = [news[i : i + batch_size] for i in range(0, len(news), batch_size)]
    n = len(batches)
    for i, batch in enumerate(batches, 1):
        prompt = _ai_build_prompt(batch, profile, descriptions)
        ok = True
        err = ""
        by_name: dict[str, dict] = {}
        try:
            raw = chat_fn(cfg, prompt, system=_AI_SYSTEM, temperature=0.2, timeout=timeout)
            arr = _extract_json_array(raw)
            by_name = {item.get("name", ""): item for item in arr if isinstance(item, dict)}
        except Exception as e:  # 单批失败不拖垮整次：整批降级不值得装
            ok = False
            err = repr(e)[:200]

        for c in batch:
            name = c.get("name", "")
            item = by_name.get(name)
            if item is not None:
                verdict = _map_verdict(str(item.get("verdict", "")))
                reason = str(item.get("reason", "")).strip() or "模型未给理由"
            elif not ok:
                verdict = V_NOT_WORTH
                reason = f"模型调用/解析失败：{err}"
            else:
                verdict = V_NOT_WORTH
                reason = "模型未给出该候选判断"
            # usability 从 install_list 透传的 map 取（dedup decision 不带 usability），
            # 否则 MCP 候选一律误标 ready（如 github 需凭证被当 ready）
            judgments.append(
                Judgment(
                    name=name,
                    decision="new",
                    verdict=verdict,
                    reason=reason,
                    mode="ai",
                    form=c.get("form", "Skill"),
                    usability=usability.get(name, "ready"),
                )
            )

        if on_batch is not None:
            on_batch(i, n, len(batch), ok)
    return judgments


# ---- 积木 F：doctor 自检 recommend_health（呼应 D21）-----------------------------


def recommend_health(cfg) -> list[str]:
    """判断步三模式可用性自检（D21）。返回人话描述行，纯函数不 IO、不烧 token。

    keyword/manual 恒可用（无 key 不走死路，D21 安全网）；ai 需文本模型完整。
    cfg 用 duck-typing（只需 cfg.text.is_complete），不硬 import Config，松耦合。
    """
    text_ok = bool(getattr(getattr(cfg, "text", None), "is_complete", False))
    return [
        "keyword：可用（无 key、不烧 token，纯规则打分）",
        "manual ：可用（无 key、不烧 token，人工勾选）",
        f"ai     ：{'可用（文本模型已配，会烧 token）' if text_ok else '不可用（TEXT 缺；用 keyword/manual 兜底，D21）'}",
    ]
