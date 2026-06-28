"""零 token 自测：llm.clip_temperature 按模型自动裁剪 temperature（#16）。

不连网、不真调 LLM。验证：
  ① Claude 系列传 1.5 → 裁到 1.0 + warning
  ② Claude 系列传 -0.1 → 裁到 0.0 + warning
  ③ Claude 合法值 0.2 原样返回
  ④ OpenAI/DeepSeek/Gemini 合法范围 [0,2] 不拦
  ⑤ 未知模型走默认 [0,2]
  ⑥ 边界值 0.0 / 1.0 / 2.0 不裁、不发 warning
"""

from __future__ import annotations

import warnings

from skillbrew import llm

# ---------- 范围识别 ----------


def test_claude_range():
    """Claude 前缀模型 → [0,1]。"""
    assert llm._temp_range_for("claude-3-5-sonnet-20241022") == (0.0, 1.0)
    assert llm._temp_range_for("Claude-Opus-4") == (0.0, 1.0)
    assert llm._temp_range_for("anthropic.claude-3") == (0.0, 1.0)


def test_openai_deepseek_gemini_range():
    """OpenAI/DeepSeek/Gemini 前缀 → [0,2]。"""
    assert llm._temp_range_for("gpt-4o") == (0.0, 2.0)
    assert llm._temp_range_for("o1-mini") == (0.0, 2.0)
    assert llm._temp_range_for("deepseek-chat") == (0.0, 2.0)
    assert llm._temp_range_for("gemini-1.5-pro") == (0.0, 2.0)


def test_unknown_defaults_to_0_2():
    """未知模型名 → [0,2] 兜底（安全默认，不拦 OpenAI 类代理）。"""
    assert llm._temp_range_for("some-custom-model") == (0.0, 2.0)
    assert llm._temp_range_for("") == (0.0, 2.0)


# ---------- clip_temperature 行为 ----------


def test_claude_clips_high():
    """Claude 传 1.5 → 裁到 1.0 并发 warning。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert llm.clip_temperature("claude-3-5-sonnet", 1.5) == 1.0
        assert len(w) == 1
        assert "1.0" in str(w[0].message)


def test_claude_clips_low():
    """Claude 传 -0.1 → 裁到 0.0 并发 warning。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert llm.clip_temperature("claude-3-opus", -0.1) == 0.0
        assert len(w) == 1
        assert "0.0" in str(w[0].message)


def test_claude_valid_passthrough():
    """Claude 合法范围内原样返回、无 warning。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert llm.clip_temperature("claude-3-5-sonnet", 0.2) == 0.2
        assert llm.clip_temperature("claude-3-5-sonnet", 0.0) == 0.0
        assert llm.clip_temperature("claude-3-5-sonnet", 1.0) == 1.0
        # 合法值不发 warning
        assert not [x for x in w if "temperature" in str(x.message).lower()]


def test_openai_accepts_up_to_2():
    """OpenAI/DeepSeek/Gemini 传 1.5 不裁、无 warning。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert llm.clip_temperature("gpt-4o", 1.5) == 1.5
        assert llm.clip_temperature("deepseek-chat", 2.0) == 2.0
        assert llm.clip_temperature("gemini-1.5-pro", 1.8) == 1.8
        assert not [x for x in w if "temperature" in str(x.message).lower()]


def test_openai_clips_above_2():
    """任何模型传 > 2 都裁（连 OpenAI 也不收 2.0 以上）。"""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert llm.clip_temperature("gpt-4o", 2.5) == 2.0
        assert len(w) == 1
