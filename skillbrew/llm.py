"""可插拔 LLM 客户端（D15）。

文本走 TEXT_* 组（DeepSeek），视觉走 VISION_* 组（Agnes）。
两者都 OpenAI 兼容，统一用 openai SDK；换供应商只改 .env，代码不动。
"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from openai import OpenAI

from .config import Config, ProviderConfig


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
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    r = client.chat.completions.create(
        model=model or cfg.text.model,
        messages=messages,
        temperature=temperature,
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
    url = _image_to_url(image)
    r = client.chat.completions.create(
        model=model or cfg.vision.model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            }
        ],
        temperature=temperature,
        timeout=timeout,
    )
    return (r.choices[0].message.content or "").strip()
