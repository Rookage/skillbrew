#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agnes 接入冒烟测试
验证 MVP 技术路线的命门三件事：
  [0] key + base_url 通不通（顺带列出确切 model id）
  [1] 文本模型 agnes-2.0-flash 通不通（字幕消化/执行计划靠它）
  [2] 视觉模型 agnes-1.5-flash 能不能【真看图】（关键帧视觉靠它）

零第三方图片依赖：测试图用标准库手搓一张「左红右蓝」PNG，
若模型答出"左红右蓝"即证明它真的在看图，而非瞎蒙。
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
TEXT_MODEL = os.environ.get('LLM_TEXT_MODEL', 'agnes-2.0-flash')
VISION_MODEL = os.environ.get('LLM_VISION_MODEL', 'agnes-1.5-flash')

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

print('base_url   =', BASE_URL)
print('key 前缀   =', API_KEY[:7] + '...' + API_KEY[-4:], '（已脱敏）')
print('文本模型   =', TEXT_MODEL)
print('视觉模型   =', VISION_MODEL)
print('=' * 64)

# ---------- [0] 列出可用模型（拿确切 model id，避免猜错名）----------
print('\n[0] 可用模型列表 (GET /v1/models):')
try:
    models = client.models.list()
    ids = sorted(m.id for m in models.data)
    for i in ids:
        print('   -', i)
    if not ids:
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

# ---------- [2] 视觉模型（真·看图验证）----------
print('\n[2] 视觉模型测试:', VISION_MODEL)


def make_half_half_png(w=120, h=120):
    """标准库手搓一张「左红右蓝」PNG。若模型答出此布局，证明它真看图。"""
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
t0 = time.time()
try:
    r = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "这张图里有哪些颜色？它们是怎么排列的？一句话回答。"},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]}],
    )
    print('   [OK] 成功 (%.1fs)' % (time.time() - t0))
    print('   回复:', r.choices[0].message.content.strip())
    print('   (期望: 左红右蓝 —— 答对即证明模型真在看图)')
except Exception as e:
    print('   [FAIL] 失败:', repr(e)[:300])

print('\n' + '=' * 64)
print('冒烟测试结束。')
