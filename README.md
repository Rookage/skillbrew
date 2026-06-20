# skillbrew — AI 能力包管理器

> 把视频 / 报告 / 文件 / 网页丢进去，自动消化成"AI 可执行计划"，授权后按步安装成 AI 的真实能力（Skill / MCP / 代码 / 配置），并维护一张可去重、可累加、可视化的能力台账。开源，本地优先。

项目章程（目标 / 技术路线 / 架构 / 依赖 / 里程碑）见上级目录 [`PROJECT_CHARTER.md`](../PROJECT_CHARTER.md)。

## 现状

骨架阶段。已就绪：

- 分角色配置（`.env`，已 gitignore）：文本组 `TEXT_*` = DeepSeek；视觉组 `VISION_*` = Agnes
- 可插拔 LLM 客户端（D15）：`chat_text` / `chat_vision`，换供应商只改 `.env`
- 自检命令 `skillbrew doctor`

下一步（MVP）：B站单源 → 字幕 + 关键帧消化 → 执行计划 → 人工审 → 装 1 个 Skill → 台账 + 单次报告。

## 安装

```bash
# 1. 复制配置并填入你自己的 key
cp .env.example .env
#   编辑 .env：TEXT_API_KEY（DeepSeek）、VISION_API_KEY（Agnes）

# 2. 安装（可编辑，注册 skillbrew 命令）
pip install -e .
```

依赖：`openai`（必装）。视频获取 / ASR 走可选依赖 `pip install -e ".[media]"`（yt-dlp + faster-whisper，较大）。

## 自检

```bash
skillbrew doctor            # 配置 + 文本连通 + 视觉模型列表（快）
skillbrew doctor --vision   # 额外跑一次真·看图（Agnes ~5min/张）
skillbrew config            # 打印解析后的配置（key 脱敏）
```

也可不安装直接跑：`PYTHONPATH=. python3 -m skillbrew doctor`。

## 配置说明

| 组 | 环境变量 | 默认供应商 | 用途 |
|----|---------|-----------|------|
| 文本 | `TEXT_BASE_URL` / `TEXT_API_KEY` / `TEXT_MODEL` | DeepSeek（deepseek-chat） | 消化 / 执行计划 |
| 视觉 | `VISION_BASE_URL` / `VISION_API_KEY` / `VISION_MODEL` | Agnes（agnes-1.5-flash） | 关键帧看图 |

为什么视觉用 Agnes：DeepSeek 官方 API 视觉暂未开放（命门实测，见章程 r9）；Agnes 是当前唯一已测真看图的官方 API。

## 安全

- `.env` 已被 `.gitignore` 忽略（D14）。仓库只放 `.env.example` 占位。
- ⚠️ 上 GitHub 前，请到各供应商控制台重置 key。
