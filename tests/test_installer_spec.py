"""D23 通用安装器 · 第 1 步离线单测：catalog↔spec↔item 往返字段同构（回归门禁）。

这是 D23 最关键的不变式：无论 MCP 装法来自 catalog 种子、本地缓存还是 AI 推断，
``spec_to_item`` 产出的 item dict 必须与 ``verify.group_mcp_items`` 命中分支**逐字段
同构**。否则下游 install/dedup/recommend/record 会因字段形状不一致而崩——这条测试就是
"形状不变"的守门人。

全离线：group_mcp_items 纯查表（不联网/不调 LLM/不耗配额，D18），不调 _probe_stars
（stars 恒 None），故无 monkeypatch、无网络即可跑。
"""
from __future__ import annotations

from skillbrew import installer, verify
from skillbrew import mcp_catalog


def _plan_with_all_catalog_entries() -> dict:
    """造一个 plan：6 条 catalog MCP 全部命中（traced_sources.name 用 entry 规范名）。"""
    entries = list(mcp_catalog.CATALOG.values())
    traced_sources = [{"name": e.name} for e in entries]
    capabilities = [
        {"form": "MCP", "source_ref": str(i + 1), "name": f"能力-{e.name}"}
        for i, e in enumerate(entries)
    ]
    return {"traced_sources": traced_sources, "capabilities": capabilities}


def test_catalog_spec_item_roundtrip_isomorphic():
    """回归门禁核心：spec_to_item(from_catalog_entry(entry)) 必须与 group_mcp_items
    命中分支产出的 item dict 逐字段相等。

    覆盖全部 6 条 catalog：playwright / filesystem / sequential-thinking / context7
    / github / sqlite。任何字段（含空值约定、usability 优先级、mcp 子字典）不一致即失败。
    """
    plan = _plan_with_all_catalog_entries()
    items, unresolved = verify.group_mcp_items(plan)

    # 6 条全部命中，无 unresolved
    assert len(items) == len(mcp_catalog.CATALOG)
    assert unresolved == []

    by_name = {e.name: e for e in mcp_catalog.CATALOG.values()}
    for item in items:
        entry = by_name[item["name"]]
        spec = installer.from_catalog_entry(entry)
        got = installer.spec_to_item(
            spec,
            source_ref=item["source_ref"],
            capability_name=item["capability_name"],
        )
        assert got == item, (
            f"{item['name']} 字段不一致:\n  got  = {got}\n  want = {item}"
        )


def test_spec_to_item_field_set_matches_group_mcp_items():
    """item 字段集与 group_mcp_items 命中分支完全一致（不多不少）。"""
    plan = _plan_with_all_catalog_entries()
    items, _ = verify.group_mcp_items(plan)
    expected_keys = set(items[0].keys())
    for item in items:
        entry = mcp_catalog.lookup(item["name"])
        spec = installer.from_catalog_entry(entry)
        got = installer.spec_to_item(spec, source_ref=item["source_ref"])
        assert set(got.keys()) == expected_keys
        assert set(got["mcp"].keys()) == {"transport", "command", "args", "scope"}


def test_spec_to_item_omits_transparency_fields():
    """过程透明度字段（provenance/verify_ok/missing/trace）绝不泄漏进 item dict。

    AI 推断路径的 spec 带这些字段供报告展示，但下游 install/dedup 只认 group_mcp_items
    的 item 形状，故 spec_to_item 必须把它们剥掉。
    """
    spec = installer.InstallSpec(
        name="custom-mcp",
        command="npx",
        args=("-y", "custom-mcp"),
        invoke_hint="自定义工具",
        repo="o/custom",
        url="https://github.com/o/custom",
        provenance="ai",
        verify_ok=True,
        missing=["OPENAI_API_KEY"],
        trace=["ai 推断", "试跑通过"],
    )
    item = installer.spec_to_item(spec, source_ref="3", capability_name="自定义能力")

    # 透明度字段不进 item
    assert "provenance" not in item
    assert "verify_ok" not in item
    assert "missing" not in item
    assert "trace" not in item

    # 字段集与 catalog 命中分支同构
    plan = _plan_with_all_catalog_entries()
    items, _ = verify.group_mcp_items(plan)
    assert set(item.keys()) == set(items[0].keys())
    assert item["usability"] == "ready"
    assert item["mcp"]["args"] == ["-y", "custom-mcp"]


def test_usability_priority_optional_credential_does_not_trigger_needs_credentials():
    """usability 优先级关键不变式（回归门禁）：

    - github 有必填 credential_env → needs_credentials
    - context7 只有 optional_credential_env（CONTEXT7_API_KEY）→ ready（有则更好、无也能跑）
    - filesystem 无 credential_env 但 needs_config → needs_config
    - playwright 无 credential_env 无 needs_config 但 needs_runtime → needs_runtime
    - sequential-thinking 全空 → ready
    """
    plan = _plan_with_all_catalog_entries()
    items, _ = verify.group_mcp_items(plan)
    by_name = {it["name"]: it for it in items}

    assert by_name["github"]["usability"] == "needs_credentials"
    assert by_name["context7"]["usability"] == "ready"  # optional 不算必填
    assert by_name["filesystem"]["usability"] == "needs_config"
    assert by_name["sqlite"]["usability"] == "needs_config"
    assert by_name["playwright"]["usability"] == "needs_runtime"
    assert by_name["sequential-thinking"]["usability"] == "ready"


def test_empty_value_conventions_match_group_mcp_items():
    """空值约定（回归门禁）：与 group_mcp_items 逐字一致。

    - credential_env 空 → None（不是 []）
    - env_template 空 → {}（不是 None）
    - post_install_steps 空 → []（不是 None）
    """
    plan = _plan_with_all_catalog_entries()
    items, _ = verify.group_mcp_items(plan)
    by_name = {it["name"]: it for it in items}

    # sequential-thinking：无 credential_env / 无 env_template / 无 post_install_steps
    st = by_name["sequential-thinking"]
    spec = installer.from_catalog_entry(mcp_catalog.lookup("sequential-thinking"))
    got = installer.spec_to_item(spec)
    assert got["credential_env"] is None  # 不是 []
    assert got["env_template"] == {}  # 不是 None
    assert got["post_install_steps"] == []  # 不是 None
    # 与 group_mcp_items 产出一致
    assert got["credential_env"] == st["credential_env"]
    assert got["env_template"] == st["env_template"]
    assert got["post_install_steps"] == st["post_install_steps"]

    # github：有 credential_env / 有 env_template / 有 post_install_steps，列表化一致
    gh = by_name["github"]
    spec = installer.from_catalog_entry(mcp_catalog.lookup("github"))
    got = installer.spec_to_item(spec)
    assert got["credential_env"] == ["GITHUB_PERSONAL_ACCESS_TOKEN"]
    assert got["env_template"] == {"GITHUB_PERSONAL_ACCESS_TOKEN": ""}
    assert got["credential_env"] == gh["credential_env"]


def test_from_catalog_entry_marks_preverified_seed():
    """catalog 种子转出的 spec 标 provenance=catalog、verify_ok=True、missing=[]。"""
    for entry in mcp_catalog.CATALOG.values():
        spec = installer.from_catalog_entry(entry)
        assert spec.provenance == "catalog"
        assert spec.verify_ok is True
        assert spec.missing == []
        assert spec.trace  # 非空，留了溯源说明
