# SkillBREW — 技能酿造局

> **刷视频 → 收藏吃灰 → 重复装 → 越来越臃肿 → 装完不会调...**
>
> 技能酿造局：丢链接进去，酿出可装的能力，自动去重，装完出报告，让你清楚 Agent 里有什么、怎么调。

---

## 痛点链条

你遇到过吗？

- 刷到「Claude Code 必装 6 个 MCP」视频，收藏了，然后...忘了
- 想装的时候，又要重新看视频、找链接、配环境
- 装完发现：「等等，我之前是不是装过？」
- 装了一堆，越来越臃肿，启动越来越慢
- 最后：装是装了，但怎么用？文档在哪？

**从「信息过载」到「能力落地」，中间差一个酿造局。**

---

## 能力矩阵

### 🧪 消化能力

把「信息」酿成「可执行计划」

- **多源采集**：B站 / 抖音 / YouTube / 文件 / 网页，丢链接就行
- **智能理解**：字幕 + 关键帧视觉，提取「装什么、怎么装、依赖什么」
- **自动溯源**：GitHub 一手核实，不装过期包、不抄二手教程
- **多形态识别**：Skill / MCP / 代码 / 配置 / Prompt，不挑活

**技术实现**：
- 文本理解：DeepSeek（deepseek-chat）
- 视觉理解：Agnes（agnes-1.5-flash）
- 字幕提取：yt-dlp + faster-whisper
- 关键帧抽取：ffmpeg

### 🔧 安装能力

把「计划」变成「真实能力」

- **多形态支持**：Skill / MCP / 代码 / 配置 / Prompt，不挑活
- **授权门**：默认 dry-run，`--approve` 才真落盘，你说了算
- **去重机制**：三层从严判定（名字 / 描述 / 语义），不重复装
- **回滚支持**：装错了？一条命令退回干净状态

**安装方式**：
| 形态 | 落地位置 | 安装方式 |
|------|---------|---------|
| Skill | `.claude/skills/<name>/` | 整目录拷贝（含 SKILL.md） |
| MCP | `~/.claude.json` 或 `.mcp.json` | `claude mcp add` 或 JSON 合并 |
| 代码 | 项目内模块 | 直接写入 |
| 配置 | `CLAUDE.md` 或片段库 | 追加或覆盖 |
| Prompt | 片段库或 Skill | 模板化存储 |

### 📊 管理能力

把「装了什么」变成「清楚知道」

- **台账 RECORD.md**：装了 56 个能力，每个来源、时间、调用方式
- **看板 DASHBOARD.md**：可视化统计，一眼看清能力分布
- **回滚支持**：装错了？一条命令退回干净状态
- **D22 装完前必做**：透明标注「装了不能立刻用 / 要凭证」的能力

---

## 从混乱到清晰

```
刷视频 → 收藏吃灰 → 重复装 → 越来越臃肿 → 装完不会调
   ↓
SkillBREW 接管
   ↓
丢链接 → 自动消化 → 去重判断 → 授权安装 → 台账记录
   ↓
清楚知道：装了 56 个能力，4 个 MCP 服务器，每个怎么调
```

---

## 8 步管线

```
采集 → 理解 → 消化 → 溯源 → 判断 → 去重 → 安装 → 记录
```

每一步都可独立运行、可审计、可回滚。不是黑箱，是酿造工艺。

| 步骤 | 输入 | 输出 | 关键模块 | 产物 |
|------|------|------|---------|------|
| 1. 采集 | URL/文件 | 原始素材（字幕/截图/HTML） | `fetch.py` | `sources/<id>/raw/` |
| 2. 理解 | 原始素材 | 结构化笔记 | `understand.py` | `sources/<id>/notes.json` |
| 3. 消化 | 笔记 | 执行计划 | `plan.py` | `sources/<id>/plan.json` |
| 4. 溯源 | 计划 | 验证后的计划 | `verify.py` | `sources/<id>/install_list.json` |
| 5. 判断 | 验证后计划 | 评分排序 | `recommend.py` | `sources/<id>/judgment.json` |
| 6. 去重 | 评分结果 | 去重决策 | `dedup.py` | `sources/<id>/dedup.json` |
| 7. 安装 | 去重决策 | 已装能力 | `install.py` | `~/.claude/skills/` 或 `~/.claude.json` |
| 8. 记录 | 安装结果 | 台账/看板 | `record.py` | `RECORD.md` + `DASHBOARD.md` |

---

## 现状

**骨架阶段，但已跑通端到端。**

- ✅ 8 步管线全通（B站 / 抖音双源验证）
- ✅ 多形态支持（Skill + MCP，已真装 4 个 MCP 服务器）
- ✅ 去重机制（三层从严，名字 / 描述 / 语义）
- ✅ 可视化报告（RECORD.md 台账 + DASHBOARD.md 看板）
- ✅ 授权门（默认 dry-run，`--approve` 才真装）
- ✅ D22 装完前必做（透明标注「装了不能立刻用 / 要凭证」的能力）

**已真装验证的 MCP 服务器：**

| 服务器 | 用途 | 状态 |
|--------|------|------|
| `@playwright/mcp` | 浏览器自动化（打开网页、点击、填表、检查报错） | ✅ 已装 |
| `@modelcontextprotocol/server-filesystem` | 文件系统访问（读写指定目录） | ✅ 已装 |
| `@modelcontextprotocol/server-sequential-thinking` | 结构化思考（复杂问题分步推理） | ✅ 已装 |
| `@upstash/context7-mcp` | 官方文档查询（查最新库文档） | ✅ 已装 |
| `@modelcontextprotocol/server-github` | GitHub 操作（需 PAT 凭证） | ⏳ 待凭证 |

**技术栈：**

- 分角色配置（`.env`，已 gitignore）：文本组 `TEXT_*` = DeepSeek；视觉组 `VISION_*` = Agnes
- 可插拔 LLM 客户端（D15）：`chat_text` / `chat_vision`，换供应商只改 `.env`
- 自检命令 `skillbrew doctor`
- Python 3.10+，openai SDK，yt-dlp，faster-whisper，ffmpeg

---

## 安装

```bash
# 1. 复制配置并填入你自己的 key
cp .env.example .env
#   编辑 .env：TEXT_API_KEY（DeepSeek）、VISION_API_KEY（Agnes）

# 2. 安装（可编辑，注册 skillbrew 命令）
pip install -e .
```

依赖：`openai`（必装）。视频获取 / ASR 走可选依赖 `pip install -e ".[media]"`（yt-dlp + faster-whisper，较大，按需装）。

## 快速开始

**示例：从抖音视频安装 6 个 MCP 服务器**

```bash
# 1. 采集 + 理解 + 消化（生成执行计划）
skillbrew fetch https://v.douyin.com/LcTwRFgJqas/
skillbrew understand data/sources/douyin_7650401218518387995/
skillbrew plan data/sources/douyin_7650401218518387995/

# 2. 溯源 + 判断 + 去重（验证 + 评分 + 去重）
skillbrew verify data/sources/douyin_7650401218518387995/
skillbrew recommend data/sources/douyin_7650401218518387995/
skillbrew dedup data/sources/douyin_7650401218518387995/

# 3. 安装（默认 dry-run，看计划）
skillbrew install data/sources/douyin_7650401218518387995/

# 4. 确认无误，真装
skillbrew install data/sources/douyin_7650401218518387995/ --approve

# 5. 生成台账 + 看板
skillbrew record data/sources/douyin_7650401218518387995/
```

每一步都可独立运行、可审计。中间产物在 `data/sources/<id>/` 下，随时可查。

---

## 自检

```bash
skillbrew doctor            # 配置 + 文本连通 + 视觉模型列表（快）
skillbrew doctor --vision   # 额外跑一次真·看图（Agnes ~5min/张）
skillbrew config            # 打印解析后的配置（key 脱敏）
```

也可不安装直接跑：`PYTHONPATH=. python3 -m skillbrew doctor`。

---

## 配置说明

| 组 | 环境变量 | 默认供应商 | 用途 |
|----|---------|-----------|------|
| 文本 | `TEXT_BASE_URL` / `TEXT_API_KEY` / `TEXT_MODEL` | DeepSeek（deepseek-chat） | 消化 / 执行计划 |
| 视觉 | `VISION_BASE_URL` / `VISION_API_KEY` / `VISION_MODEL` | Agnes（agnes-1.5-flash） | 关键帧看图 |

**为什么分两组配置？**

- **文本组（DeepSeek）**：消化视频内容、生成执行计划、评分排序——这些是纯文本推理任务，DeepSeek 性价比高
- **视觉组（Agnes）**：看关键帧截图、提取视频画面信息——DeepSeek 官方 API 视觉暂未开放（命门实测，见章程 r9），Agnes 是当前唯一已测真看图的官方 API
- **可插拔设计（D15）**：`chat_text` / `chat_vision` 两个函数封装，换供应商只改 `.env`，代码零改动

**为什么视觉用 Agnes 而不是其他？**

DeepSeek 官方 API 视觉能力暂未开放（章程 r9 命门实测）。我们测了多个供应商，Agnes 是当前唯一已验证能真看图的官方 API。虽然慢（~5min/张），但能完成关键帧理解任务。

---

## 安全

**凭证保护**

- `.env` 已被 `.gitignore` 忽略（D14）。仓库只放 `.env.example` 占位。
- ⚠️ 上 GitHub 前，请到各供应商控制台重置 key。

**授权门（Authorization Gate）**

```
用户输入 URL
    ↓
采集 → 理解 → 消化 → 溯源 → 判断 → 去重
    ↓
install（默认 dry-run）
    ↓
显示安装计划：
  - 要装 5 个 MCP 服务器
  - playwright（needs_runtime：首次调用下载浏览器内核）
  - filesystem（needs_config：需指定允许访问目录）
  - github（needs_credentials：需 PAT 凭证，默认跳过）
  - ...
    ↓
用户确认？
  ├─ 否 → 结束，什么都不装
  └─ 是 → install --approve → 真装 → 记录台账
```

**D22 装完前必做**

透明标注「装了不能立刻用 / 要凭证」的能力，不黑箱：

| 标注 | 含义 | 示例 |
|------|------|------|
| `ready` | 装完立刻能用 | sequential-thinking / context7 |
| `needs_runtime` | 首次调用需下载依赖 | playwright（下载浏览器内核 ~200MB） |
| `needs_config` | 需手动配置参数 | filesystem（需指定允许访问目录） |
| `needs_credentials` | 需配置凭证 | github（需 PAT） |

---

## 项目章程

目标 / 技术路线 / 架构 / 依赖 / 里程碑，见 [`PROJECT_CHARTER.md`](./PROJECT_CHARTER.md)。

交接文档（Step 5 完成记录），见 [`HANDOFF.md`](./HANDOFF.md)。

---

**SkillBREW — 让 AI 能力从「信息过载」到「清楚知道」。**
