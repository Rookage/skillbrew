"""schema 子包测试：每个 dataclass roundtrip + SCHEMA_VERSION + 前向兼容 + 类型守护。"""

from __future__ import annotations

import pytest

from skillbrew.schema import (
    SCHEMA_VERSION,
    DedupReport,
    InstallList,
    KeyframeAlignItem,
    KeyframeVisionItem,
    PlanData,
    ResolveTrace,
    TranscriptData,
    models,
)

ROUNDTRIP_CASES = [
    (
        "transcript",
        TranscriptData(
            segments=[{"start": 0.0, "end": 1.5, "text": "你好"}],
            text="你好",
            language="zh",
        ),
    ),
    ("align", KeyframeAlignItem(t=3.0, file="kf_3s.jpg", nearby_subtitle="字幕")),
    (
        "vision_ok",
        KeyframeVisionItem(t=3, file="kf_3s.jpg", ok=True, desc="红按钮", elapsed=5.2),
    ),
    (
        "vision_err",
        KeyframeVisionItem(t=3, file="kf_3s.jpg", ok=False, error="Timeout", attempts=3),
    ),
    (
        "plan",
        PlanData(
            source_title="T",
            summary="S",
            capabilities=[{"name": "c1"}],
            _raw_model="deepseek-chat",
            _verify={"how_resolved": "ocr_corrected"},
        ),
    ),
    (
        "dedup",
        DedupReport(
            source_video="bv1",
            summary={"new": 1, "merge": 0, "skip": 0, "total": 1},
        ),
    ),
    (
        "install_list",
        InstallList(source_video="bv1", form="Skill", total=2, items=[{"name": "a"}]),
    ),
    ("resolve_trace", ResolveTrace(items={"a": {"provenance": "x"}}, unresolved=[])),
]


def test_schema_version_is_stable_string():
    assert SCHEMA_VERSION == "1.0"
    assert models.SCHEMA_VERSION == SCHEMA_VERSION


@pytest.mark.parametrize("name,obj", ROUNDTRIP_CASES)
def test_roundtrip(name, obj):
    """to_dict → from_dict → to_dict 三段相等（往返无损）。"""
    d = obj.to_dict()
    assert isinstance(d, dict)
    assert type(obj).from_dict(d).to_dict() == d


def test_from_dict_ignores_unknown_keys():
    """前向兼容：产物未来加字段不崩，未知键被静默丢弃，已知字段照常取到。"""
    obj = TranscriptData.from_dict(
        {
            "segments": [{"start": 0.0, "text": "x"}],
            "text": "x",
            "language": "en",
            "future_field_v2": 42,  # 未来版本加的字段
        }
    )
    assert obj.text == "x"
    assert obj.language == "en"
    assert len(obj.segments) == 1
    assert not hasattr(obj, "future_field_v2")


def test_install_list_ignores_other_form_keys():
    """三形态异构：读 MCP 形态产物时，Skill 形态的 verified_repo 等键被忽略不崩。"""
    mcp_payload = {
        "source_video": "yt1",
        "form": "MCP",
        "install_method": "mcp_register",
        "items": [{"name": "playwright", "command": "npx"}],
        "unresolved": [],
        "mcp_only_field": {"needs_config": True},  # MCP 独有，InstallList 没声明
    }
    il = InstallList.from_dict(mcp_payload)
    assert il.form == "MCP"
    assert il.items[0]["name"] == "playwright"
    assert not hasattr(il, "mcp_only_field")


def test_from_dict_rejects_non_dict():
    """传非 dict 抛 TypeError，不静默吞错类型。"""
    with pytest.raises(TypeError):
        TranscriptData.from_dict("not a dict")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        KeyframeVisionItem.from_dict([1, 2, 3])  # type: ignore[arg-type]


def test_defaults_are_safe():
    """默认值可变字段用 default_factory，多实例不共享引用（防 dataclass 经典坑）。"""
    a = TranscriptData()
    b = TranscriptData()
    a.segments.append({"start": 0.0})
    assert b.segments == []  # b 不被污染


def test_empty_transcript_roundtrip():
    """ASR 降级落盘的空 transcript（segments=[]/text=''）也能无损往返。"""
    empty = TranscriptData(segments=[], text="", language="")
    assert TranscriptData.from_dict(empty.to_dict()) == empty
