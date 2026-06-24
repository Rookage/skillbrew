"""零 token 自测：验证 D22「怎么调用装好的技能」渲染（record.py），不碰 LLM、不要 key。

跑法：PYTHONPATH=. python tests/test_record_d22.py
覆盖：① _trigger 抠 'Use when…' ② _trigger 无触发词取首句兜底 ③ _trigger 长文截断
      ④ _invoke_hint 按形态给调用机制（Skill/MCP/代码/配置）⑤ 真装→表格逐个列
      ⑥ dry-run 未落盘→优雅降级（不空列候选）⑦ 空批→无可调用项
这是 R1（装了不自动调用）痛点的 MVP 桥接：报告说清调用方式，人照着调。
"""
import sys
from skillbrew import record as R


def _fake_g(*, installed, sessions, rec=None, forms=None, descs=None,
            resolve_trace=None):
    """造一个最小可用的 g（同 _gather 的真口径键）。installed=[name,...]，sessions=[]
    表 dry-run；forms/descs 给每个名字的形态/描述，缺省 Skill + 含 Use when。
    resolve_trace 模拟 D23 resolve_trace.json sidecar 内容。"""
    by_name = {}
    reg = {}
    for n in installed:
        by_name[n] = {"display_name": n, "description": (descs or {}).get(n, f"Use when user wants {n}.")}
        reg[n] = {"display_name": n, "form": (forms or {}).get(n, "Skill")}
    return {
        "new_installed": [{"name": n, "category": "Productivity"} for n in installed],
        "src_sessions": sessions,
        "recommend": rec,
        "by_name": by_name,
        "reg_active_by_name": reg,
        "resolve_trace": resolve_trace,
        "il": {},
    }


def test_trigger_use_when():
    """① description 含 'Use when…' → 从那里起取作触发提示词。"""
    t = R._trigger("Generate designs. Use when user wants to design an API, explore options.")
    assert t.startswith("Use when"), f"应从 Use when 起取: {t}"
    assert "Generate designs" not in t, "Use when 前的内容不该出现"
    print("  [1] _trigger 抠 'Use when…'：✓ 从触发条件起取")


def test_trigger_fallback_sentence():
    """② 无 'Use when' → 取首句兜底（中文句号/英文句点）。"""
    t = R._trigger("Turn a loose idea into a map. Drive them to resolution.")
    assert t == "Turn a loose idea into a map", f"应取首句: {t!r}"
    t2 = R._trigger("先做这个。再做那个。")
    assert t2 == "先做这个", f"中文句号切首句: {t2!r}"
    print("  [2] _trigger 无触发词取首句：✓ 中英文句点兜底")


def test_trigger_truncate():
    """③ 超长 → 截到 110 字符带 …。"""
    long = "Use when " + "x" * 200
    t = R._trigger(long)
    assert len(t) == 110 and t.endswith("…"), f"应截断 110 + …: len={len(t)} end={t[-1]}"
    print("  [3] _trigger 长文截断：✓ 110 字符 + …")


def test_invoke_hint_by_form():
    """④ 按形态给调用机制——Skill 点名/自动加载，MCP 暴露工具，代码/配置各有入口。"""
    s = R._invoke_hint("foo", "Skill")
    assert "foo" in s and "自动加载" in s, f"Skill: {s}"
    assert "暴露工具" in R._invoke_hint("x", "MCP"), "MCP 应说暴露工具"
    assert "代码" in R._invoke_hint("x", "代码"), "代码形态"
    assert "设置" in R._invoke_hint("x", "配置"), "配置形态"
    assert "自动加载" in R._invoke_hint("x", None), "form 缺省当 Skill"
    print("  [4] _invoke_hint 按形态：✓ Skill/MCP/代码/配置/缺省")


def test_section_real_install():
    """⑤ 真装（sessions 非空）→ 表格逐个列，每个技能一行，含 @名/形态/触发/调用。"""
    g = _fake_g(installed=["ask-matt", "review", "obsidian-vault"], sessions=[{"id": 1}])
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "怎么调用" in out and "装完就能用" in out, "应有引导句"
    assert "| # | @名 | 形态" in out, "应有表头"
    # 3 个技能 → 3 条数据行
    rows = [ln for ln in out.splitlines() if ln.startswith("| ") and "ask-matt" in ln or "review" in ln or "obsidian-vault" in ln]
    assert len(rows) == 3, f"应 3 行数据: {rows}"
    assert "`ask-matt`" in out and "`review`" in out and "`obsidian-vault`" in out
    assert "Use when" in out, "触发提示词应出现"
    assert "自动加载" in out, "调用机制应出现"
    print("  [5] 真装→表格逐个列：✓ 3 技能各一行 + 表头 + 触发 + 调用")


def test_section_dry_run():
    """⑥ dry-run（sessions 空）→ D22 反盲盒也列出候选表格（装前看清要配什么）。"""
    g = _fake_g(installed=["a", "b", "c"], sessions=[])
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "未落盘" in out, f"应有降级措辞: {out}"
    assert "| # | @名 | 形态" in out, "dry-run 也应铺候选表格（D22 反盲盒）"
    assert "`a`" in out and "`b`" in out and "`c`" in out, "候选应全部列出"
    print("  [6] dry-run 未落盘→D22 反盲盒列候选：✓ 铺表 + 未落盘提示")


def test_section_empty_install():
    """⑦ 真装但本批无 new 能力 → 「无可调用项」，不铺空表。"""
    g = _fake_g(installed=[], sessions=[{"id": 1}])  # 装过但本批没新的
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "无可调用项" in out, f"应说无可调用项: {out}"
    assert "| # | @名" not in out
    print("  [7] 真装但本批空→无可调用项：✓ 不铺空表")


def test_section_with_recommend():
    """⑧ 带 recommend（真装 + approved 子集）→ 末尾注 approved 数（D20 挑着买）。"""
    g = _fake_g(installed=["a", "b"], sessions=[{"id": 1}],
                rec={"mode": "keyword", "approved": ["a"]})
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "approved" in out and "挑着买" in out, f"应注 approved/挑着买: {out}"
    print("  [8] 带 recommend→注 approved 子集：✓ D20 挑着买标注")


# ---- D23: provenance / resolve_trace / unresolved 展示 ----

def test_provenance_label_all_values():
    """⑨ _provenance_label 五种值全映射正确，未知值回退原值。"""
    assert R._provenance_label("cached") == "缓存命中"
    assert R._provenance_label("catalog") == "catalog 种子"
    assert R._provenance_label("ai") == "AI 推断（已验证）"
    assert R._provenance_label("ai_unverified") == "AI 推断（未验证）"
    assert R._provenance_label("unresolved") == "未解析"
    assert R._provenance_label("bogus") == "bogus"  # 未知值回退原文
    assert R._provenance_label("") == "未知"  # 空字符串→未知
    assert R._provenance_label(None) == "未知"  # None→未知
    print("  [9] _provenance_label 五种值全映射：✓ cached/catalog/ai/ai_unverified/unresolved/未知")


def test_section_with_provenance_column():
    """⑩ 真装 + resolve_trace 有数据 → 表头含「装法来源」列，每行显示中文 provenance。"""
    rt = {
        "items": {
            "a": {"provenance": "cached", "trace": ["L1 缓存命中"], "missing": []},
            "b": {"provenance": "ai", "trace": ["L3 AI 推断"], "missing": ["KEY_X"]},
            "c": {"provenance": "catalog", "trace": [], "missing": []},
        },
        "unresolved": [],
    }
    g = _fake_g(installed=["a", "b", "c"], sessions=[{"id": 1}], resolve_trace=rt)
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "装法来源" in out, f"表头应有装法来源列: {out}"
    assert "缓存命中" in out, "a 应标缓存命中"
    assert "AI 推断（已验证）" in out, "b 应标 AI 推断"
    assert "catalog 种子" in out, "c 应标 catalog 种子"
    print("  [10] 真装+resolve_trace→装法来源列：✓ 缓存命中/AI推断/catalog种子")


def test_section_provenance_fallback_unknown():
    """⑪ resolve_trace 有但 item 缺 provenance → 显示「未知」。"""
    rt = {"items": {"x": {}}, "unresolved": []}
    g = _fake_g(installed=["x"], sessions=[{"id": 1}], resolve_trace=rt)
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "未知" in out, f"缺 provenance 应显示未知: {out}"
    print("  [11] resolve_trace 缺 provenance→未知：✓")


def test_section_without_resolve_trace():
    """⑫ 无 resolve_trace（旧源或 install 未写 sidecar）→ 优雅降级，不崩，表头仍含装法来源列。"""
    g = _fake_g(installed=["a", "b"], sessions=[{"id": 1}], resolve_trace=None)
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "装法来源" in out, "表头仍应有装法来源列"
    assert "未知" in out, "无 resolve_trace 时 provenance 应显示未知"
    print("  [12] 无 resolve_trace→优雅降级：✓ 表头仍含装法来源+值显示未知")


def test_section_unresolved_subsection():
    """⑬ resolve_trace 含 unresolved → 表格后追加「未解析」小节，列出卡点原因和缺失项。"""
    rt = {
        "items": {"a": {"provenance": "catalog", "trace": [], "missing": []}},
        "unresolved": [
            {"name": "ghost", "reason": "试跑失败", "missing": ["API_KEY"]},
            {"name": "shadow", "reason": "catalog 无此条目", "missing": ["repo_url", "install_command"]},
        ],
    }
    g = _fake_g(installed=["a"], sessions=[{"id": 1}], resolve_trace=rt)
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "未解析" in out, "应有未解析小节标题"
    assert "ghost" in out and "shadow" in out, "两个 unresolved 条目都应出现"
    assert "试跑失败" in out, "reason 应显示"
    assert "API_KEY" in out and "repo_url" in out, "missing 列表应逐项显示"
    print("  [13] unresolved 小节：✓ 卡点原因+缺失项逐条列出")


def test_section_unresolved_fallback_il():
    """⑭ resolve_trace 无 unresolved 但 il 有 → 从 il.unresolved 兜底取。"""
    g = _fake_g(installed=["a"], sessions=[{"id": 1}], resolve_trace={"items": {}, "unresolved": []})
    g["il"] = {"unresolved": [{"name": "fallback", "reason": "兜底", "missing": ["X"]}]}
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "未解析" in out and "fallback" in out, "应从 il.unresolved 兜底取"
    print("  [14] unresolved 从 il 兜底：✓")


def test_section_empty_unresolved_no_subsection():
    """⑮ 无 unresolved 条目 → 不追加未解析小节。"""
    rt = {"items": {"a": {"provenance": "catalog", "trace": [], "missing": []}}, "unresolved": []}
    g = _fake_g(installed=["a"], sessions=[{"id": 1}], resolve_trace=rt)
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "未解析" not in out, "无 unresolved 条目不应出现未解析小节"
    print("  [15] 无 unresolved→不追加小节：✓")


def test_section_unresolved_missing_empty():
    """⑯ unresolved 条目缺 missing 字段 → 显示「—」而非崩。"""
    rt = {
        "items": {},
        "unresolved": [{"name": "no-missing", "reason": "未知原因"}],
    }
    g = _fake_g(installed=[], sessions=[{"id": 1}], resolve_trace=rt)
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "未解析" in out and "no-missing" in out, "unresolved 小节应出现"
    assert "—" in out, "缺 missing 字段应显示 —"
    print("  [16] unresolved 缺 missing→显示「—」：✓")


def test_section_unresolved_no_name():
    """⑰ unresolved 条目缺 name → 显示「?」而非崩。"""
    rt = {
        "items": {},
        "unresolved": [{"reason": "无名字的条目", "missing": []}],
    }
    g = _fake_g(installed=[], sessions=[{"id": 1}], resolve_trace=rt)
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "?" in out, "缺 name 应显示 ?"
    print("  [17] unresolved 缺 name→显示「?」：✓")


def test_section_unresolved_default_reason():
    """⑱ unresolved 条目缺 reason → 兜底默认文案。"""
    rt = {
        "items": {},
        "unresolved": [{"name": "no-reason", "missing": []}],
    }
    g = _fake_g(installed=[], sessions=[{"id": 1}], resolve_trace=rt)
    out = "\n".join(R._d22_invoke_section(g, heading="## 8. 怎么调用\n"))
    assert "装法未知" in out, "缺 reason 应显示默认文案"
    print("  [18] unresolved 缺 reason→默认文案：✓")


if __name__ == "__main__":
    print("record.py D22「怎么调用」零 token 自测（不调 LLM）：")
    test_trigger_use_when()
    test_trigger_fallback_sentence()
    test_trigger_truncate()
    test_invoke_hint_by_form()
    test_section_real_install()
    test_section_dry_run()
    test_section_empty_install()
    test_section_with_recommend()
    # D23: provenance / resolve_trace / unresolved
    test_provenance_label_all_values()
    test_section_with_provenance_column()
    test_section_provenance_fallback_unknown()
    test_section_without_resolve_trace()
    test_section_unresolved_subsection()
    test_section_unresolved_fallback_il()
    test_section_empty_unresolved_no_subsection()
    test_section_unresolved_missing_empty()
    test_section_unresolved_no_name()
    test_section_unresolved_default_reason()
    print("\n全部通过 ✓  D22 调用方式渲染 + D23 provenance 展示就绪")
    sys.exit(0)
