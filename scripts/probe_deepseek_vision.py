#!/usr/bin/env python3
"""
DeepSeek V4 视觉 API 格式探测（命门验证）

背景：probe_provider.py 用标准 OpenAI `image_url` content 格式调
api.deepseek.com/v1/chat/completions，被拒：
  BadRequestError 400 "unknown variant `image_url`, expected `text`"
说明 V4 Pro 在 OpenAI 兼容端点上，content 数组只收 {type:text}，不收图。

本脚本验证最可能的替代格式（来自第三方资料交叉核实）：
  假设1（最可能）：DeepSeek 提供 Anthropic 兼容端点 /anthropic/v1/messages，
    V4 Pro 视觉走 Anthropic 图片块格式 {type:image, source:{type:base64,...}}。
    依据：多篇资料称 V4 Pro 用 Anthropic 兼容接口调，base_url=api.deepseek.com/anthropic；
    且 V4 定位"替代 Claude"，走 Anthropic 协议合情理。
    分别试 deepseek-v4-pro（强）与 deepseek-v4-flash（快，批量关键帧更划算）。
  假设2（低信心，便宜）：OpenAI 端点 + php.cn 说法——图片作 message 顶层 image_data 字段。
  假设3（低信心，便宜）：OpenAI 端点 + message 顶层 image_url 字段(data URI)。

用 stdlib urllib，无第三方依赖。
"""

import base64
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENV_PATH = os.path.join(REPO, ".env")


def load_env(path):
    if not os.path.exists(path):
        print(f"[ERR] 找不到 {path}")
        sys.exit(1)
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()


load_env(ENV_PATH)
API_KEY = os.environ["LLM_API_KEY"]


def make_half_half_png(w=120, h=120):
    """手搓「左红右蓝」PNG。答对此布局即证明真看图。"""

    def chunk(typ, data):
        c = typ + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    half = w // 2
    red, blue = bytes([255, 0, 0]), bytes([0, 0, 255])
    raw = b"".join(b"\x00" + red * half + blue * (w - half) for _ in range(h))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


img_b64 = base64.b64encode(make_half_half_png()).decode()
Q = "这张图里有哪些颜色？它们是怎么排列的？一句话回答。"


def post(url, headers, body, timeout=150):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return time.time() - t0, resp.status, resp.read().decode("utf-8", "replace"), None
    except urllib.error.HTTPError as e:
        return time.time() - t0, e.code, e.read().decode("utf-8", "replace"), None
    except Exception as e:
        return time.time() - t0, None, "", repr(e)


def extract_text(resp_json):
    try:
        d = json.loads(resp_json)
        # anthropic 格式：content=[{type:text,text:...}, ...]
        if "content" in d and isinstance(d["content"], list):
            t = " ".join(b.get("text", "") for b in d["content"] if b.get("type") == "text").strip()
            if t:
                return t
        # openai 格式
        if "choices" in d:
            return d["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return ""


def judge(ans):
    hit = ("红" in ans or "red" in ans.lower()) and ("蓝" in ans or "blue" in ans.lower())
    return "✅ 答对(真看图)" if hit else "⚠️ 未命中红+蓝"


print("key 前缀 =", API_KEY[:7] + "..." + API_KEY[-4:])
print("=" * 64)

# ---------- 假设1：Anthropic 兼容端点 ----------
url_a = "https://api.deepseek.com/anthropic/v1/messages"
headers_a = {
    "x-api-key": API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}
for m in ["deepseek-v4-pro", "deepseek-v4-flash"]:
    print(f"\n[假设1] Anthropic 兼容端点  model={m}")
    print("   POST", url_a)
    body = {
        "model": m,
        "max_tokens": 256,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": Q},
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": img_b64},
                    },
                ],
            }
        ],
    }
    dt, code, txt, err = post(url_a, headers_a, body)
    print(f"   状态={code} 耗时={dt:.1f}s err={err}")
    ans = extract_text(txt) if code == 200 else ""
    print("   响应(前500):", (ans or txt)[:500])
    if ans:
        print("   判定:", judge(ans))

# ---------- 假设2：OpenAI 端点 + 顶层 image_data ----------
print("\n[假设2] OpenAI 端点 + message 顶层 image_data 字段")
url_o = "https://api.deepseek.com/v1/chat/completions"
headers_o = {"Authorization": f"Bearer {API_KEY}", "content-type": "application/json"}
body = {
    "model": "deepseek-v4-pro",
    "messages": [{"role": "user", "content": Q, "image_data": img_b64}],
}
dt, code, txt, err = post(url_o, headers_o, body)
print(f"   状态={code} 耗时={dt:.1f}s err={err}")
ans = extract_text(txt) if code == 200 else ""
print("   响应(前500):", (ans or txt)[:500])
if ans:
    print("   判定:", judge(ans))

# ---------- 假设3：OpenAI 端点 + 顶层 image_url(data URI) ----------
print("\n[假设3] OpenAI 端点 + message 顶层 image_url 字段(data URI)")
body = {
    "model": "deepseek-v4-pro",
    "messages": [{"role": "user", "content": Q, "image_url": f"data:image/png;base64,{img_b64}"}],
}
dt, code, txt, err = post(url_o, headers_o, body)
print(f"   状态={code} 耗时={dt:.1f}s err={err}")
ans = extract_text(txt) if code == 200 else ""
print("   响应(前500):", (ans or txt)[:500])
if ans:
    print("   判定:", judge(ans))

print("\n" + "=" * 64)
print("命中 200 且答对红+蓝 的假设，即为 DeepSeek V4 视觉的正确接入格式。")
