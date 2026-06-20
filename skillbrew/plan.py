"""plan：消化 → 执行计划（MVP-3）。

把"语音字幕(transcript.txt) + 关键帧视觉描述(keyframe_visions.json)"喂给文本
LLM（DeepSeek，deepseek-chat），融合成一份结构化执行计划：

  - 能力清单：这条素材能教会 AI 什么能力（每项带画面/字幕依据）
  - 每项形态：Skill / MCP / 代码 / 配置 —— 消化后才定，不预设（D2 综合型）
  - 安装步骤：每项怎么落地成实物
  - 溯源：一手源头（GitHub repo / 文档 URL），从画面文字抽出、标注待核实（D6）

计划落 plan.json，供审核门（MVP-4）转 Markdown 给用户授权后再安装。

设计要点：
  - 视觉描述自带时间戳 t，与字幕对齐后一起喂，让 LLM 知道"说到 X 时画面是 Y"
  - 强约束 JSON 输出（system 指明只出 JSON；解析时容错剥 ```json 围栏）
  - temperature=0.2 求稳；模型走 cfg.text（DeepSeek），不硬编码
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .config import load_config
from . import llm

SYSTEM = (
    "你是 skillbrew 的消化引擎。输入是一段科技短视频的「语音字幕」和若干「关键帧视觉描述」"
    "（每条视觉描述带时间戳 t 秒，可与字幕对齐）。你的任务：把两者融合成一份结构化执行计划，"
    "告诉用户这条素材能教会 AI 什么能力、每项能力该以什么形态安装、怎么安装、一手源头在哪。"
    "要求：①只依据给出的字幕和视觉描述，不编造没出现的内容；②能力要具体可落地，"
    "别泛泛而谈；③信息不足处如实标注（evidence 写明依据，install_steps 写'待溯源核实后补'）；"
    "④**只输出一个 JSON 对象，不要任何解释、不要 markdown 代码围栏**。"
)

SCHEMA_HINT = """\
按此结构输出 JSON（字段名固定，值用中文）：
{
  "source_title": "素材标题（无则从内容概括）",
  "source_type": "video",
  "summary": "一句话：这条素材讲了什么、对 AI 能力建设有何价值",
  "traced_sources": [
    {"kind": "github_repo|doc_url|paper|other", "url": "完整 URL", "name": "名称", "note": "画面/字幕依据 + 是否待核实"}
  ],
  "capabilities": [
    {
      "name": "能力名（短）",
      "description": "这个能力做什么、解决什么问题",
      "evidence": "依据：哪条字幕/哪个关键帧(t=Ns)看到的",
      "form": "Skill | MCP | code | config",
      "form_reason": "为什么选这个形态",
      "install_steps": ["步骤1（可执行的具体动作）", "步骤2", "..."],
      "source_ref": "对应 traced_sources 第几项（1 基）或留空"
    }
  ],
  "open_questions": ["信息不足或待用户确认的点"]
}"""


def _build_prompt(transcript: str, visions: list[dict]) -> str:
    vis_text = "\n".join(
        f"[t={v['t']}s 关键帧 {v.get('file','')}] {v['desc']}"
        for v in visions
    )
    return (
        f"=== 语音字幕（ASR） ===\n{transcript}\n\n"
        f"=== 关键帧视觉描述（Agnes 真看图） ===\n{vis_text}\n\n"
        f"=== 输出要求 ===\n{SCHEMA_HINT}\n"
    )


def _extract_json(text: str) -> dict:
    """从模型回复里抠出 JSON：去围栏、取第一个 {...} 平衡块。"""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # 退而求其次：找第一个平衡的花括号块
    start = s.find("{")
    if start < 0:
        raise ValueError(f"回复里找不到 JSON:\n{text[:500]}")
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start : i + 1])
    raise ValueError(f"JSON 花括号不平衡:\n{text[:500]}")


def digest(source_dir: Path, *, timeout: float = 180.0) -> dict:
    """对一个源目录跑消化，落 plan.json 并返回计划 dict。"""
    source_dir = Path(source_dir)
    transcript = (source_dir / "transcript.txt").read_text(encoding="utf-8").strip()
    vis_file = source_dir / "keyframe_visions.json"
    visions = json.loads(vis_file.read_text(encoding="utf-8")) if vis_file.exists() else []
    visions = [v for v in visions if v.get("ok")]
    if not transcript and not visions:
        raise RuntimeError(f"字幕和视觉都为空: {source_dir}")

    cfg = load_config()
    prompt = _build_prompt(transcript, visions)
    raw = llm.chat_text(cfg, prompt, system=SYSTEM, temperature=0.2, timeout=timeout)
    plan = _extract_json(raw)
    plan["_raw_model"] = cfg.text.model  # 留痕用的什么模型
    (source_dir / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (source_dir / "plan_raw.txt").write_text(raw, encoding="utf-8")  # 原始回复留档便于排错
    return plan


# ---- 直接运行：python -m skillbrew.plan <源目录> ----
def _main() -> int:
    if len(sys.argv) < 2:
        print("用法: python -m skillbrew.plan <源目录>")
        print("     源目录需含 transcript.txt + keyframe_visions.json（先跑 understand + 视觉批处理）")
        return 1
    src = Path(sys.argv[1])
    print(f"[消化] DeepSeek 融合字幕 + {len(json.loads((src/'keyframe_visions.json').read_text(encoding='utf-8')))} 条视觉描述...")
    plan = digest(src)
    print(f"[OK] 计划存 {src/'plan.json'}")
    print(f"  标题: {plan.get('source_title','')}")
    print(f"  摘要: {plan.get('summary','')}")
    print(f"  能力 {len(plan.get('capabilities',[]))} 项:")
    for c in plan.get("capabilities", []):
        print(f"    - [{c.get('form','?')}] {c.get('name','')}  (依据: {c.get('evidence','')[:40]})")
    print(f"  溯源 {len(plan.get('traced_sources',[]))} 项:")
    for ts in plan.get("traced_sources", []):
        print(f"    - {ts.get('kind','')}: {ts.get('url','')}  ({ts.get('note','')[:40]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
