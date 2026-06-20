#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用 LLM provider 探测脚本（D15 可插拔验证）
读 .env 里配置的 provider，验证三件事：
  [0] key + base_url 通不通 + 列出确切 model id（避免猜错模型名）
  [1] 文本模型通不通（LLM_TEXT_MODEL）
  [2] 视觉模型【真看图】（遍历候选 model 名，发手搓「左红右蓝」图，答对即证明真看图）

当前用途：核实 DeepSeek 视觉 API（2026-06-18 上线「识图模式」，确切 model id 待确认）。
换 provider 只改 .env，脚本不动（D15 模型无关/可插拔）。
"""
import os, sys, base64, zlib, struct, time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENV_PATH = os.path.join(REPO, '.env')


def load_env(path):
    if not os.path.exists(path):
        print(f'[ERR] 找不到配置文件 {path}')
        sys.exit(1)
    for line in open(path, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip()


load_env(ENV_PATH)
from openai import OpenAI

BASE_URL = os.environ['LLM_BASE_URL']
API_KEY = os.environ['LLM_API_KEY']
TEXT_MODEL = os.environ.get('LLM_TEXT_MODEL', '')
VISION_MODEL = os.environ.get('LLM_VISION_MODEL', '')

client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=180)

print('base_url   =', BASE_URL)
print('key 前缀   =', API_KEY[:7] + '...' + API_KEY[-4:], '（已脱敏）')
print('文本模型   =', TEXT_MODEL)
print('视觉模型   =', VISION_MODEL, '(配置值，下方会实探)')
print('=' * 64)

# ---------- [0] 列模型 ----------
print('\n[0] 可用模型列表 (GET /v1/models):')
listed = []
try:
    models = client.models.list()
    listed = sorted(m.id for m in models.data)
    for i in listed:
        print('   -', i)
    if not listed:
        print('   (返回为空)')
except Exception as e:
    print('   [WARN] 列模型失败（不影响后续测试）:', repr(e)[:200])

# ---------- [1] 文本模型 ----------
print('\n[1] 文本模型测试:', TEXT_MODEL)
t0 = time.time()
try:
    r = client.chat.completions.create(
        model=TEXT_MODEL,
        messages=[{"role": "user", "content": "用一句话介绍你自己，并说明你的模型名称。"}],
    )
    print('   [OK] 成功 (%.1fs)' % (time.time() - t0))
    print('   回复:', r.choices[0].message.content.strip())
except Exception as e:
    print('   [FAIL] 失败:', repr(e)[:300])

# ---------- [2] 视觉模型探测（真·看图验证）----------
def make_half_half_png(w=120, h=120):
    """标准库手搓一张「左红右蓝」PNG。答对此布局即证明真看图。"""
    def chunk(typ, data):
        c = typ + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    half = w // 2
    red, blue = bytes([255, 0, 0]), bytes([0, 0, 255])
    raw = b''.join(b'\x00' + red * half + blue * (w - half) for _ in range(h))
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw)) +
            chunk(b'IEND', b''))


img_b64 = base64.b64encode(make_half_half_png()).decode()
data_uri = f'data:image/png;base64,{img_b64}'

# 候选视觉模型名：配置值 + 列表返回 + 已知候选，去重保序
candidates = []
for m in [VISION_MODEL] + listed + ['deepseek-v4-pro', 'deepseek-vl2-chat',
                                     'deepseek-vl', 'deepseek-vision', 'deepseek-chat']:
    if m and m not in candidates:
        candidates.append(m)

print('\n[2] 视觉模型探测（手搓左红右蓝图，答对即真看图）:')
print('   候选 model:', candidates)
for m in candidates:
    print(f'\n   -- 试 {m} --')
    t0 = time.time()
    try:
        r = client.chat.completions.create(
            model=m,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": "这张图里有哪些颜色？它们是怎么排列的？一句话回答。"},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]}],
            timeout=150,
        )
        ans = r.choices[0].message.content.strip()
        print('      [OK] 成功 (%.1fs)' % (time.time() - t0))
        print('      回复:', ans)
        hit = ('红' in ans or 'red' in ans.lower()) and ('蓝' in ans or 'blue' in ans.lower())
        print('      真看图:', '✅ 答对' if hit else '⚠️ 答案未命中红+蓝')
    except Exception as e:
        print('      [FAIL]', repr(e)[:200])

print('\n' + '=' * 64)
print('探测结束。')
