"""可插拔 LLM 客户端（D15）。

文本走 TEXT_* 组（DeepSeek），视觉走 VISION_* 组（Agnes）。
两者都 OpenAI 兼容，统一用 openai SDK；换供应商只改 .env，代码不动。
"""
from __future__ import annotations

import base64
import mimetypes
import os
import sys
import warnings
from pathlib import Path

from openai import OpenAI

from .config import Config, ProviderConfig
from .errors import ConfigError
from .errors import ConfigError


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


def _client(p: ProviderConfig, *, label: str = "LLM") -> OpenAI:
    """创建 OpenAI 兼容客户端。配置不全时给交互式引导（D16/D21）。

    - 有 TTY：逐项交互式输入，自动写入 .env
    - 无 TTY（headless/管道）：打印清晰配置指南
    """
    if not (p.base_url and p.api_key):
        _interactive_config(p, label)
    if not (p.base_url and p.api_key):
        raise ConfigError(
            f"{label} 配置不全：需要 BASE_URL + API_KEY",
            hint="请 cp .env.example .env 并编辑填入 key，或重跑让 skillbrew 交互式引导。",
        )
    return OpenAI(base_url=p.base_url, api_key=p.api_key)


def _interactive_config(p: ProviderConfig, label: str) -> None:
    """交互式填入缺失的配置项，写入 .env 文件。"""
    from .config import env_path

    if not sys.stdin.isatty():
        _print_config_guide(label)
        return

    print(f"\n{'='*50}")
    print(f"  {label} 配置缺失")
    print(f"  当前：BASE_URL={p.base_url or '(空)'}  KEY={'***' if p.api_key else '(空)'}")
    print(f"{'='*50}")
    print("  是否现在交互式填入？[y/N] ", end="", flush=True)
    try:
        ans = sys.stdin.readline().strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "n"
    if ans not in ("y", "yes"):
        _print_config_guide(label)
        return

    env_file = env_path()
    if not env_file.exists():
        _bootstrap_env(env_file)

    updates: dict[str, str] = {}
    if not p.base_url:
        val = _prompt_env("  BASE_URL", p.base_url, "https://api.deepseek.com").strip()
        if val:
            updates["TEXT_BASE_URL" if "TEXT" in label.upper() or "文本" in label else "VISION_BASE_URL"] = val
    if not p.api_key:
        prefix = "TEXT" if "TEXT" in label.upper() or "文本" in label else "VISION"
        val = _prompt_env(f"  {prefix}_API_KEY", "").strip()
        if val:
            updates[f"{prefix}_API_KEY"] = val
    if not p.model:
        prefix = "TEXT" if "TEXT" in label.upper() or "文本" in label else "VISION"
        val = _prompt_env(f"  {prefix}_MODEL", p.model, "deepseek-chat" if "TEXT" in label.upper() else "agnes-1.5-flash").strip()
        if val:
            updates[f"{prefix}_MODEL"] = val

    if updates:
        _write_env(env_file, updates)
        for k, v in updates.items():
            os.environ[k] = v
        print(f"  ✅ 已写入 {env_file}（{len(updates)} 项）\n")
    else:
        print("  未填入任何配置。\n")


def _prompt_env(name: str, current: str, default: str = "") -> str:
    hint = f"（默认 {default}）" if default else ""
    print(f"  {name}{hint}: ", end="", flush=True)
    try:
        val = sys.stdin.readline().strip()
    except (EOFError, KeyboardInterrupt):
        return current or default
    return val or current or default


def _print_config_guide(label: str) -> None:
    from .config import env_path
    env = env_path()
    print(f"\n  [{label}] 配置引导：")
    if not env.exists():
        print(f"  1. cp .env.example .env")
        print(f"  2. 编辑 {env}，填入你的 API key")
    else:
        print(f"  编辑 {env}，检查 TEXT_*/VISION_* 配置是否完整")
    print(f"  🇨🇳 国内用户：DeepSeek (platform.deepseek.com) 文本模型推荐")
    print(f"  🇬🇱 视觉模型：Agnes (platform.agnes-ai.com) 或 NVIDIA NIM (build.nvidia.com)\n")


def _bootstrap_env(path) -> None:
    example = path.parent / ".env.example"
    if example.exists():
        import shutil
        shutil.copy(example, path)
        print(f"  📋 已从 {example} 复制模板\n")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "# skillbrew 配置 (D15 可插拔)\n"
            "# 文本模型（必备，D21）\n"
            "TEXT_BASE_URL=https://api.deepseek.com\n"
            "TEXT_API_KEY=\n"
            "TEXT_MODEL=deepseek-chat\n"
            "# 视觉模型（可选，缺则降级为纯字幕消化）\n"
            "VISION_BASE_URL=\n"
            "VISION_API_KEY=\n"
            "VISION_MODEL=agnes-1.5-flash\n",
            encoding="utf-8",
        )
        print(f"  📋 已生成 {path}\n")


def _write_env(path, updates: dict[str, str]) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    lines = existing.splitlines(keepends=True)
    written = set()
    new_lines: list[str] = []
    for line in lines:
        for k, v in updates.items():
            if line.strip().startswith(f"{k}=") or line.strip().startswith(f"{k} ="):
                new_lines.append(f"{k}={v}\n")
                written.add(k)
                break
        else:
            new_lines.append(line)
    for k, v in updates.items():
        if k not in written:
            new_lines.append(f"{k}={v}\n")
    path.write_text("".join(new_lines), encoding="utf-8")


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
