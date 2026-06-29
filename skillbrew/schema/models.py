"""schema：跨阶段 JSON 产物的轻量类型壳（纯标准库 dataclass）。

skillbrew 8 步管线每步在 ``data/sources/<id>/`` 落若干 JSON 中间产物。
本模块给其中 7 个**跨阶段**产物套一层类型壳 + ``SCHEMA_VERSION``，提供
``to_dict()`` / ``from_dict()``，让产物形状可校验、可序列化、前向兼容。

设计原则（对齐章程 D7 防臃肿 / D18 刻舟求剑 / 「纯标准库」硬约束）：

- **纯标准库**（dataclasses），不引 pydantic，零新依赖。
- **顶层壳 + 嵌套 dict 兜底**：只为字段稳定的产物建顶层 dataclass；
  LLM 产出（plan.capabilities）/ 三形态异构（install_list.items）等
  可变嵌套结构用 ``dict[str, Any]`` 承接，不臆造强类型，避免过度设计。
- **from_dict 忽略未知键**（前向兼容）：产物字段增减不崩，呼应「现取现算不写死」。
- **第一版只加新文件、不动老代码、不强制调用**：老代码继续直接
  ``json.dump``/``json.load`` dict 不受影响；dataclass 渐进式迁移。
- **数组类产物**（keyframes_align / keyframe_visions）建**元素** dataclass，
  顶层仍是 list，落盘形状零改动。

覆盖的 7 个产物（落盘文件名）：
  1. transcript.json       — understand.transcribe（ASR 字幕）
  2. keyframes_align.json  — understand.align_keyframes（帧-时间戳对齐，数组）
  3. keyframe_visions.json — understand.describe_keyframes（每帧视觉描述，数组）
  4. plan.json             — plan.digest（消化计划，LLM 产出）
  5. dedup.json             — dedup.dedup（去重报告）
  6. install_list.json      — verify（三形态异构安装清单）
  7. resolve_trace.json     — install executor（D23 resolve-pass sidecar）
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field, fields
from typing import Any

#: 产物 schema 版本。未来字段破坏性变更时 +1；from_dict 的前向兼容策略
#: 保证旧版本产物仍可读，故首版无需把版本写进每个产物文件（不改落盘形状）。
SCHEMA_VERSION = "1.0"


def _from_dict(cls: type, data: dict[str, Any]) -> Any:
    """通用反序列化：按 dataclass 已声明字段取值，**忽略未知键**（前向兼容）。

    传非 dict 抛 TypeError，避免静默吞错类型。
    """
    if not isinstance(data, dict):
        raise TypeError(
            f"{cls.__name__}.from_dict 期望 dict，收到 {type(data).__name__}"
        )
    known = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


def _to_dict(obj: Any) -> dict[str, Any]:
    """通用序列化：dataclass → dict（深拷贝嵌套；产物文件小，开销可忽略）。"""
    return dataclasses.asdict(obj)


# ---- 1. transcript.json（understand.transcribe，ASR 字幕） ----
@dataclass(slots=True)
class TranscriptData:
    """``{segments, text, language}``。segments 每项 = ``{start, end, text}``。"""

    segments: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    language: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranscriptData:
        return _from_dict(cls, data)


# ---- 2. keyframes_align.json（understand.align_keyframes，数组） ----
@dataclass(slots=True)
class KeyframeAlignItem:
    """数组元素：``{t, file, nearby_subtitle}``。"""

    t: float = 0.0
    file: str = ""
    nearby_subtitle: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyframeAlignItem:
        return _from_dict(cls, data)


# ---- 3. keyframe_visions.json（understand.describe_keyframes，数组） ----
@dataclass(slots=True)
class KeyframeVisionItem:
    """数组元素：``{t, file, ok, desc, elapsed, attempts, error?}``。

    ``ok=True`` 时带 desc；``ok=False`` 时带 error（3 次重试全败）。
    """

    t: int = 0
    file: str = ""
    ok: bool = True
    desc: str = ""
    elapsed: float = 0.0
    attempts: int = 1
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KeyframeVisionItem:
        return _from_dict(cls, data)


# ---- 4. plan.json（plan.digest，消化计划，LLM 产出） ----
@dataclass(slots=True)
class PlanData:
    """消化计划。capabilities/traced_sources 由 LLM 产出，字段可变 → dict 兜底。"""

    source_title: str = ""
    source_type: str = "video"
    summary: str = ""
    traced_sources: list[dict[str, Any]] = field(default_factory=list)
    capabilities: list[dict[str, Any]] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    _raw_model: str = ""  # digest 留痕用的什么文本模型
    _verify: dict[str, Any] = field(default_factory=dict)  # verify 回填的纠错块

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanData:
        return _from_dict(cls, data)


# ---- 5. dedup.json（dedup.dedup，去重报告） ----
@dataclass(slots=True)
class DedupReport:
    """去重报告。decisions/baseline/summary 等结构由 dedup 构造，dict 兜底。"""

    source_video: str = ""
    install_list_repo: str = ""
    install_list_form: str = ""
    baseline: dict[str, Any] = field(default_factory=dict)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    by_form: dict[str, Any] = field(default_factory=dict)
    unresolved: list[Any] = field(default_factory=list)
    note: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DedupReport:
        return _from_dict(cls, data)


# ---- 6. install_list.json（verify，三形态异构安装清单） ----
@dataclass(slots=True)
class InstallList:
    """安装清单。Skill / MCP / repo 三形态字段不同 → 异构键用 dict 兜底，
    from_dict 自动忽略他形态的键。items/skills 是同引用双键别名，互不影响。"""

    source_video: str = ""
    form: str = ""
    install_method: str = ""
    total: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)
    skills: list[dict[str, Any]] = field(default_factory=list)  # 兼容别名
    unresolved: list[Any] = field(default_factory=list)
    verified_repo: dict[str, Any] = field(default_factory=dict)
    branch: str = ""
    raw_base: str = ""
    note: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InstallList:
        return _from_dict(cls, data)


# ---- 7. resolve_trace.json（install executor，D23 resolve-pass sidecar） ----
@dataclass(slots=True)
class ResolveTrace:
    """``{items, unresolved}``。items = name → {provenance, trace, missing}。"""

    items: dict[str, Any] = field(default_factory=dict)
    unresolved: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResolveTrace:
        return _from_dict(cls, data)
