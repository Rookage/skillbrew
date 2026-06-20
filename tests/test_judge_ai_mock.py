"""零 token 自测：用 mock chat_fn 验证 judge_ai 管道，不碰 DeepSeek、不要 key。

跑法：PYTHONPATH=. python tests/test_judge_ai_mock.py
覆盖：① 正常 JSON 数组解析+verdict 映射 ② 模型调用抛异常→整批降级不值得装
      ③ 畸形回复（无数组）→降级 ④ on_batch 回调 ⑤ 与 merge_judgments 衔接
"""
import sys
from skillbrew import recommend as rec


def make_profile():
    return rec.Profile(
        distinct=3,
        by_category={"Productivity": 2, "Coding": 1},
        names={"existing-skill-a", "existing-skill-b", "existing-skill-c"},
        keywords={"git", "test", "code"},
    )


def make_decisions():
    # 5 条 new + 1 skip + 1 merge，模拟 dedup.json 的 decisions
    return [
        {"name": "new-skill-1", "decision": "new", "category": "Productivity", "description": "一个好用的工具"},
        {"name": "new-skill-2", "decision": "new", "category": "Coding", "description": "代码生成器"},
        {"name": "new-skill-3", "decision": "new", "category": "Coding", "description": "和个人重复"},
        {"name": "new-skill-4", "decision": "new", "category": "Misc", "description": "未完成"},
        {"name": "new-skill-5", "decision": "new", "category": "Misc", "description": "另一个"},
        {"name": "existing-skill-a", "decision": "skip", "reason": "已装", "target": "existing-skill-a"},
        {"name": "old-thing", "decision": "merge", "reason": "重叠", "target": "existing-skill-b"},
    ]


def make_descs():
    return {f"new-skill-{i}": d for i, d in enumerate(
        ["一个好用的工具", "代码生成器", "和个人重复", "未完成", "另一个"], start=1)}


def test_normal():
    """① 正常：mock 返回合法 JSON 数组，5 条 new 都被判。"""
    calls = []
    def mock_chat(cfg, prompt, system=None, temperature=0.2, timeout=120.0):
        calls.append(prompt)
        return '[{"name":"new-skill-1","verdict":"值得装","reason":"实用完整"},' \
               '{"name":"new-skill-2","verdict":"值得装","reason":"代码生成有用"},' \
               '{"name":"new-skill-3","verdict":"不值得装","reason":"与已有重叠"},' \
               '{"name":"new-skill-4","verdict":"不值得装","reason":"未完成"},' \
               '{"name":"new-skill-5","verdict":"值得装","reason":"可补充能力"}]'

    batches = []
    js = rec.judge_ai(
        make_decisions(), make_profile(),
        descriptions=make_descs(),
        cfg=object(),  # mock 不用真 cfg
        chat_fn=mock_chat,
        batch_size=10,
        on_batch=lambda i, n, bs, ok: batches.append((i, n, bs, ok)),
    )
    assert len(js) == 5, f"应判 5 条 new，实得 {len(js)}"
    by = {j.name: j for j in js}
    assert by["new-skill-1"].verdict == rec.V_WORTH
    assert by["new-skill-3"].verdict == rec.V_NOT_WORTH
    assert by["new-skill-4"].reason == "未完成"
    assert all(j.mode == "ai" for j in js), "mode 必须标 ai"
    assert len(calls) == 1, f"5 条一批应只调 1 次，实得 {len(calls)}"
    assert batches == [(1, 1, 5, True)], f"on_batch 回调错: {batches}"
    print("  [1] 正常 JSON 数组：✓ 解析+映射+mode+on_batch 全对")


def test_batch_split():
    """② 分批：batch_size=2，5 条 new 应分 3 批（2+2+1），调 3 次；
    mock 只回 new-skill-1/3 两条真实名 → 匹配判值得，其余降级不值得装（防静默漏判）。"""
    calls = []
    def mock_chat(cfg, prompt, system=None, temperature=0.2, timeout=120.0):
        calls.append(prompt)
        return '[{"name":"new-skill-1","verdict":"值得装","reason":"好"},' \
               '{"name":"new-skill-3","verdict":"值得装","reason":"好"}]'
    js = rec.judge_ai(
        make_decisions(), make_profile(),
        descriptions=make_descs(),
        cfg=object(), chat_fn=mock_chat, batch_size=2,
    )
    assert len(js) == 5
    assert len(calls) == 3, f"应分 3 批，实调 {len(calls)}"
    by = {j.name: j for j in js}
    assert by["new-skill-1"].verdict == rec.V_WORTH, "匹配名应判值得"
    assert by["new-skill-3"].verdict == rec.V_WORTH, "匹配名应判值得"
    assert by["new-skill-2"].verdict == rec.V_NOT_WORTH, "未给出的应降级"
    assert by["new-skill-5"].verdict == rec.V_NOT_WORTH, "未给出的应降级"
    print("  [2] 分批(2/批)：✓ 5 条分 3 批、匹配判值得、未给出降级不值得装")


def test_call_fails():
    """③ mock 抛异常 → 整批降级不值得装，不拖垮。"""
    def mock_chat(cfg, prompt, system=None, temperature=0.2, timeout=120.0):
        raise RuntimeError("模拟 DeepSeek 挂了")
    js = rec.judge_ai(
        make_decisions(), make_profile(),
        descriptions=make_descs(),
        cfg=object(), chat_fn=mock_chat, batch_size=10,
    )
    assert len(js) == 5
    assert all(j.verdict == rec.V_NOT_WORTH for j in js), "调用失败应全降级不值得装"
    assert "失败" in js[0].reason, f"reason 应含失败: {js[0].reason}"
    print("  [3] 模型调用异常：✓ 整批降级不值得装、reason 含失败原因")


def test_malformed():
    """④ 畸形回复（无 JSON 数组）→ 降级。"""
    def mock_chat(cfg, prompt, system=None, temperature=0.2, timeout=120.0):
        return "我觉得这些都不错，可以装。没有 JSON。"
    js = rec.judge_ai(
        make_decisions(), make_profile(),
        descriptions=make_descs(),
        cfg=object(), chat_fn=mock_chat, batch_size=10,
    )
    assert len(js) == 5
    assert all(j.verdict == rec.V_NOT_WORTH for j in js), "畸形回复应降级不值得装"
    print("  [4] 畸形回复无数组：✓ 降级不值得装成立")


def test_wrapped_object():
    """⑤ 模型把数组包进对象 {"results":[...]} → 能抠出来。"""
    def mock_chat(cfg, prompt, system=None, temperature=0.2, timeout=120.0):
        return '{"results":[{"name":"new-skill-1","verdict":"值得装","reason":"好"}]}'
    js = rec.judge_ai(
        make_decisions(), make_profile(),
        descriptions=make_descs(),
        cfg=object(), chat_fn=mock_chat, batch_size=10,
    )
    by = {j.name: j for j in js}
    assert by["new-skill-1"].verdict == rec.V_WORTH, "包对象应抠出数组"
    print("  [5] 数组包进对象：✓ 抠出 list 值成立")


def test_merge_integration():
    """⑥ 与 merge_judgments 衔接：new_js + skip/merge → 全量 7 条 Judgment。"""
    def mock_chat(cfg, prompt, system=None, temperature=0.2, timeout=120.0):
        return '[{"name":"new-skill-1","verdict":"值得装","reason":"好"}]'
    new_js = rec.judge_ai(
        make_decisions(), make_profile(),
        descriptions=make_descs(),
        cfg=object(), chat_fn=mock_chat, batch_size=10,
    )
    all_js = rec.merge_judgments(make_decisions(), new_js)
    assert len(all_js) == 7, f"应 7 条（5 new + 1 skip + 1 merge），实得 {len(all_js)}"
    by = {j.name: j for j in all_js}
    assert by["existing-skill-a"].verdict == rec.V_INSTALLED, "skip→已装"
    assert by["old-thing"].verdict == rec.V_MERGE, "merge→建议整并"
    assert by["new-skill-1"].verdict == rec.V_WORTH
    approved = rec.approved_names(all_js)
    assert approved == ["new-skill-1"], f"approved 应只含 new-skill-1: {approved}"
    print("  [6] merge_judgments 衔接：✓ 7 条全量、skip/merge 兜底、approved 正确")


def test_limit():
    """⑦ --limit 成本控制：只判前 2 条 new，其余 merge 兜底不值得装。"""
    def mock_chat(cfg, prompt, system=None, temperature=0.2, timeout=120.0):
        return '[{"name":"new-skill-1","verdict":"值得装","reason":"好"},' \
               '{"name":"new-skill-2","verdict":"值得装","reason":"好"}]'
    js = rec.judge_ai(
        make_decisions(), make_profile(),
        descriptions=make_descs(),
        cfg=object(), chat_fn=mock_chat, batch_size=10, limit=2,
    )
    assert len(js) == 2, f"limit=2 应只判 2 条，实得 {len(js)}"
    by = {j.name: j for j in js}
    assert "new-skill-1" in by and "new-skill-2" in by
    # 喂给 merge：未判的 new-3/4/5 应被兜底成不值得装
    all_js = rec.merge_judgments(make_decisions(), js)
    by_all = {j.name: j for j in all_js}
    assert by_all["new-skill-3"].verdict == rec.V_NOT_WORTH, "limit 外的 new 应兜底不值得装"
    assert by_all["new-skill-3"].mode == "(missing)"
    print("  [7] --limit 成本控制：✓ 只判前 2 条、其余兜底不值得装")


if __name__ == "__main__":
    print("judge_ai 零 token mock 自测（不调 DeepSeek）：")
    test_normal()
    test_batch_split()
    test_call_fails()
    test_malformed()
    test_wrapped_object()
    test_merge_integration()
    test_limit()
    print("\n全部通过 ✓  管道就绪，可上真模型（--limit 3 先小烧验证往返）")
    sys.exit(0)
