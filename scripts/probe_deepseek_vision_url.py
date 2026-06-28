#!/usr/bin/env python3
"""
DeepSeek V4 视觉——URL 图片变体验证（排除 base64 vs URL 变量）

上一脚本：Anthropic 端点接受请求格式(200 不报错)，但模型 4 种格式全说
"无法查看图片"且秒回——疑似图片没真正送达模型。本脚本用公网真实图片 URL
走 Anthropic 端点 source.type=url，排除"是不是只支持 URL 不支持 base64"。
若 URL 也说看不到 → 坐实官方 API 视觉未真正开放（6/18 全量上线=网页端≠API）。
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENV_PATH = os.path.join(REPO, ".env")


def load_env(path):
    if not os.path.exists(path):
        sys.exit(f"[ERR] 找不到 {path}")
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()


load_env(ENV_PATH)
API_KEY = os.environ["LLM_API_KEY"]

# 公网真实图片：Google webp gallery 的测试照片（稳定可公网访问），内容是一只坐着的狗
IMG_URL = "https://www.gstatic.com/webp/gallery/1.jpg"
Q = "用一句话描述这张图片里有什么。"

url_a = "https://api.deepseek.com/anthropic/v1/messages"
headers_a = {
    "x-api-key": API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}

for m in ["deepseek-v4-flash", "deepseek-v4-pro"]:
    print(f"\n[Anthropic 端点 + 真实 URL 图片]  model={m}")
    body = {
        "model": m,
        "max_tokens": 256,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": Q},
                    {"type": "image", "source": {"type": "url", "url": IMG_URL}},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        url_a, data=json.dumps(body).encode("utf-8"), headers=headers_a, method="POST"
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=150) as resp:
            code, txt = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        code, txt = e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        print(f"   异常: {e!r}")
        continue
    dt = time.time() - t0
    print(f"   状态={code} 耗时={dt:.1f}s")
    try:
        d = json.loads(txt)
        ans = " ".join(
            b.get("text", "") for b in d.get("content", []) if b.get("type") == "text"
        ).strip()
    except Exception:
        ans = txt
    print("   响应:", (ans or txt)[:500])

print('\n若都说"看不到图" → DeepSeek 官方 API 视觉未真正开放；若能描述出狗 → URL 方式可行。')
