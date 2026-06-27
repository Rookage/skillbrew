"""可插拔 LLM 客户端（D15）。

文本走 TEXT_* 组（DeepSeek），视觉走 VISION_* 组（Agnes）。
两者都 OpenAI 兼容，统一用 openai SDK；换供应商只改 .env，代码不动。
"""
from __future__ import annotations

import base64
import mimetypes
import warnings
from pathlib import Path

from openai import OpenAI

from .config import Config, ProviderConfig


# 已知模型/厂商 temperature 合法区间（按模型名/厂商标识匹配）。
# 顺序：更具体的前缀放前面；匹配到第一条即停；都不匹配走 DEFAULT。
# Claude 系列（Anthropic Messages API 及其 OpenAI 兼容代理）严格要求 [0,1]，
# 传 1.x 会直接报 400（#16 真踩过）。
_TEMP_RANGES: list[tuple[tuple[str, ...], float, float]] = [
    (("claude-", "anthropic."), 0.0, 1.0),
    (("gemini-",), 0.0, 2.0),       # Gemini OpenAI 兼容
    (("deepseek-",), 0.0, 2.0),     # DeepSeek 官方
    (("gpt-", "o1", "o3", "o4"), 0.0, 2.0),  # OpenAI
]
_TEMP_DEFAULT_RANGE: tuple[float, float] = (0.0, 2.0)


def _temp_range_for(model: str) -> tuple[float, float]:
    """按 model 名字返回 (lo, hi)。未知模型用默认 [0,2]。"""
    m = (model or "").lower()
    for prefixes, lo, hi in _TEMP_RANGES:
        if any(m.startswith(p) for p in prefixes):
            return (lo, hi)
    return _TEMP_DEFAULT_RANGE


def clip_temperature(model: str, temperature: float) -> float:
    """把 temperature 裁到 model 可接受范围；超界时发 warning 不报错。

    Claude 等模型对 temperature 范围比 OpenAI 严，硬传会 400。这里主动 clip，
    让配置/调用方不用记每家范围；超界给 warning 留痕，方便排查。
    """
    lo, hi = _temp_range_for(model or "")
    t = float(temperature)
    if t < lo:
        warnings.warn(
            f"temperature={t} 低于模型 {model!r} 允许下限 {lo}，已裁到 {lo}",
            stacklevel=2,
        )
        return lo
    if t > hi:
        warnings.warn(
            f"temperature={t} 高于模型 {model!r} 允许上限 {hi}，已裁到 {hi}",
            stacklevel=2,
        )
        return hi
    return t


def _client(p: ProviderConfig) -> OpenAI:
    if not (p.base_url and p.api_key):
        raise RuntimeError(
            "供应商配置不全：需要 BASE_URL + API_KEY（检查 .env 的 TEXT_* / VISION_*）"
        )
    return OpenAI(base_url=p.base_url, api_key=p.api_key)


def list_models(p: ProviderConfig) -> list[str]:
    """GET /models，返回排序后的 model id 列表。"""
    client = _client(p)
    page = client.models.list()
    return sorted(m.id for m in page.data)


def chat_text(
    cfg: Config,
    prompt: str,
    *,
    system: str | None = None,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: float = 120.0,
) -> str:
    """文本对话（消化 / 执行计划用）。返回模型回复正文。"""
    client = _client(cfg.text)
    use_model = model or cfg.text.model
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    r = client.chat.completions.create(
        model=use_model,
        messages=messages,
        temperature=clip_temperature(use_model, temperature),
        timeout=timeout,
    )
    return (r.choices[0].message.content or "").strip()


def _image_to_url(image: str | Path) -> str:
    """接受本地文件路径或 http(s) URL，返回可塞进 image_url.url 的字符串。"""
    s = str(image)
    if s.startswith("http://") or s.startswith("https://"):
        return s
    path = Path(image)
    if not path.exists():
        raise FileNotFoundError(f"图片不存在: {image}")
    mime = mimetypes.guess_type(s)[0] or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def chat_vision(
    cfg: Config,
    prompt: str,
    image: str | Path,
    *,
    model: str | None = None,
    temperature: float = 0.2,
    timeout: float = 900.0,  # Agnes 视觉~5min/张，给足超时
) -> str:
    """视觉对话（关键帧看图用）。image 可为本地路径或 http(s) URL。"""
    client = _client(cfg.vision)
    use_model = model or cfg.vision.model
    url = _image_to_url(image)
    r = client.chat.completions.create(
        model=use_model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ],
        temperature=clip_temperature(use_model, temperature),
        timeout=timeout,
    )
    return (r.choices[0].message.content or "").strip()
