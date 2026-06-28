# SkillBREW — 技能酿造局

![SkillBREW hero](docs/assets/skillbrew-hero.png)

> 把散落在视频、网页、README 和推荐清单里的 Agent 能力，酿成可验证、可安装、可追踪的一套本地能力库。

**SkillBREW** 是一个本地优先的 AI Agent 能力管理器。你丢进一个链接、视频或文档，它会采集内容、理解上下文、生成安装计划、回源验证、评估价值、检查重复项，并在你明确授权后把 Skill、MCP、代码片段或配置真实落地。安装完成后，它会留下台账和看板，让你知道自己到底装了什么、为什么装、以后怎么调用。

它不是又一个“收藏夹”。它更像一个给 Claude Code / Codex / MCP 工具链用的酒窖管家：原料可以很乱，入库必须清楚。

[GitHub Pages](https://rookage.github.io/skillbrew) · [项目章程](./PROJECT_CHARTER.md) · [贡献指南](./CONTRIBUTING.md)

---

## 为什么需要它

很多 Agent 用户的能力库不是被设计出来的，而是被“顺手装一下”堆出来的：

- 刷到“必装 MCP”视频，先收藏，后来找不到。
- 看到一个仓库很酷，复制安装命令，装完忘了怎么调用。
- 同类工具装了三遍，名字不同，功能重叠。
- 换 Claude Code / Codex 运行时后，路径、配置、MCP 注册方式又变了。
- 最后能力越来越多，但你不确定哪些可用、哪些缺 key、哪些只是躺在目录里。

SkillBREW 解决的不是“下载一个工具”这么小的事，而是 **Agent 能力从信息过载到可管理资产** 的中间层。

---

## 它做什么

### 1. 从素材里提炼能力

输入可以是 B站、抖音、YouTube、网页或纯文本。SkillBREW 会把素材采集到本地，提取字幕、关键帧和正文，再让 LLM 消化成结构化计划。

### 2. 回到源头验证

视频里说“装这个 GitHub MCP 很好用”，它不会直接信。`verify` 会回源查仓库、README、包信息、维护状态和安装线索，尽量拿一手资料修正二手推荐。

### 3. 先判断，再去重，再安装

`recommend` 负责判断“值不值得装”，`dedup` 负责判断“是不是重复”。两件事分开做：不让 AI 黑箱决定，也不让你靠记忆硬扛。

### 4. 授权后才真实落地

`install` 默认只 dry-run，显示计划；只有加 `--approve` 才会写入目录、配置或 MCP 注册文件。安装后再由 `record` 生成台账、看板和调用说明。

### 5. 同时考虑 Claude Code 和 Codex

SkillBREW 已经有运行时识别层，可以按 Claude Code / Codex 的约定切换 Skill 目录、MCP 配置路径和 clone 缓存目录。它的目标不是绑死某一家 Agent，而是管理跨 Agent 的能力资产。

---

## 8 步管线

```text
采集 -> 理解 -> 消化 -> 溯源 -> 判断 -> 去重 -> 安装 -> 记录
```

| 步骤 | 命令 | 目的 | 主要产物 |
|---|---|---|---|
| 1. 采集 | `ingest` | 把 URL / 文本 / 网页素材落到本地 | `metadata.json`、视频/音频/正文 |
| 2. 理解 | `understand` | ASR 字幕、关键帧、视觉描述 | `transcript.json`、`vision.json` |
| 3. 消化 | `plan` | 把素材整理成可执行安装计划 | `plan.json` |
| 4. 溯源 | `verify` | 回源验证仓库、MCP、repo、可用性 | `install_list.json` |
| 5. 判断 | `recommend` | 评估值得装、挑着装、跳过 | `recommend.json` |
| 6. 去重 | `dedup` | 与本地目录和历史台账比对 | `dedup.json` |
| 7. 安装 | `install` | dry-run 或授权后真实落地 | Skill / MCP / repo / 配置 |
| 8. 记录 | `record` | 生成能力台账和看板 | `RECORD.md`、`DASHBOARD.md` |

每一步都能单独跑。中间产物都留在 `data/sources/<id>/`，所以它不是不可审计的黑箱。

---

## 快速开始

```bash
git clone https://github.com/Rookage/skillbrew.git
cd skillbrew

# 注册 skillbrew 命令
pip install -e .

# 可选：视频 / ASR 能力，依赖较大，按需安装
pip install -e ".[media]"

# 自检配置；首次没有 .env 时会给出交互式引导
skillbrew doctor
```

跑一个素材：

```bash
# 一键跑前三步：采集 -> 理解 -> 消化
skillbrew run <url-or-text>

# 对生成的 source 继续做验证、评估和去重
skillbrew verify data/sources/<id>/
skillbrew recommend data/sources/<id>/
skillbrew dedup data/sources/<id>/

# 先看安装计划，不写入
skillbrew install data/sources/<id>/

# 确认后真实安装
skillbrew install data/sources/<id>/ --approve

# 生成台账和看板
skillbrew record data/sources/<id>/
```

通用 MCP 安装器实验能力：

```bash
# catalog 没收录时，让 AI 读源头仓库推断安装方法，并试跑验证
skillbrew install data/sources/<id>/ --approve --ai-infer
```

---

## 可信边界

SkillBREW 当前是 **骨架可跑通、核心链路已验证、仍在快速打磨的早期项目**。它已经具备这些能力：

- 8 步管线端到端跑通。
- B站、抖音、YouTube、网页、文本等输入源。
- Skill / MCP / repo / 配置 / Prompt 等多形态安装计划。
- 默认 dry-run，`--approve` 才写入。
- 本地扫描 + 台账扫描 + 形态感知去重。
- `recommend` 支持 keyword / manual / ai 三种判断模式。
- 结构化错误提示，尽量避免裸异常。
- Claude Code / Codex 运行时识别。
- CI 覆盖 ruff、mypy、pytest 和文档同步检查。

也有清楚的边界：

- Codex 的 MCP TOML 写入仍在演进中，相关逻辑已进入代码，但还需要更多真实场景验证。
- 大规模市场搜索和 MCP Marketplace 对接还在 RFC 阶段。
- 当前文档和架构仍在重构中，`cli.py`、`install.py`、`installer.py` 已经积累了架构债。

---

## 已验证的 MCP 种子

这些不是“全部生态”，而是当前作为 catalog / 缓存种子的预验证样本：

| MCP | 用途 | 状态 |
|---|---|---|
| `@playwright/mcp` | 浏览器自动化 | 已验证 |
| `@modelcontextprotocol/server-filesystem` | 文件系统访问 | 已验证 |
| `@modelcontextprotocol/server-sequential-thinking` | 结构化思考 | 已验证 |
| `@upstash/context7-mcp` | 官方文档查询 | 已验证 |
| `@modelcontextprotocol/server-github` | GitHub 操作 | 已验证 |
| `zcaceres/fetch-mcp` | 网页抓取到 markdown | AI 推断安装验证通过 |

暂缓项：

- `memos MCP`：没有稳定官方 npm 包，暂不默认安装。
- `MoneyPrinterTurbo`：需要额外凭证和运行环境，暂不默认配置。

---

## 架构地图

```text
              输入源
  B站 / 抖音 / YouTube / 网页 / 文本
                 |
                 v
        ingest.py  采集原料
                 |
                 v
     understand.py  字幕 + 关键帧 + 视觉理解
                 |
                 v
          plan.py  生成安装计划
                 |
                 v
        verify.py  回源验证一手资料
                 |
                 v
     recommend.py  判断价值与优先级
                 |
                 v
        dedup.py  本地能力画像 + 历史台账去重
                 |
                 v
 install.py / installer.py  dry-run / 授权安装 / AI 推断装法
                 |
                 v
       record.py  RECORD / DASHBOARD / INSTALLED_INDEX
```

几个关键模块：

- `config.py`：运行时识别、路径约定、环境变量覆盖。
- `llm.py`：OpenAI-compatible LLM 抽象，文本组和视觉组分离。
- `ingest.py`：多输入源采集，含 B站、抖音、YouTube、网页、文本。
- `understand.py`：ASR、关键帧抽取、视觉描述、空字幕兜底。
- `verify.py`：GitHub / MCP / repo 一手溯源。
- `recommend.py`：价值判断和整源建议。
- `dedup.py`：本地 Skill、MCP、repo、registry 多基准去重。
- `installer.py`：InstallSpec、缓存、catalog、AI 推断、试跑验证、缺项补全。
- `install.py`：真实写入、MCP JSON/TOML 合并、repo clone、dry-run 计划。
- `record.py`：安装台账、Dashboard、能力索引和调用提示。

---

## 配置

`.env.example` 提供两组模型配置：

| 组 | 变量 | 用途 |
|---|---|---|
| 文本 | `TEXT_BASE_URL` / `TEXT_API_KEY` / `TEXT_MODEL` | 消化、计划、判断 |
| 视觉 | `VISION_BASE_URL` / `VISION_API_KEY` / `VISION_MODEL` | 关键帧看图 |

默认推荐 NVIDIA NIM 的 Qwen3.5，因为它同时支持文本和视觉，OpenAI-compatible，中文表现好，速度也比旧视觉方案更适合本项目。你也可以换成 DeepSeek、Agnes 或其他兼容供应商。

系统依赖：

- `ffmpeg`：视频切帧、音频处理。
- `yt-dlp` / `faster-whisper`：在安装 `.[media]` 后启用视频下载和 ASR。

自检：

```bash
skillbrew doctor
skillbrew doctor --vision
skillbrew config
```

---

## 运行时中立

| 运行时 | Skill 目录 | MCP 配置 | clone 缓存 |
|---|---|---|---|
| Claude Code | `~/.claude/skills/` | `~/.claude.json` | `~/.claude/clones/` |
| Codex | `~/.codex/skills/` | `~/.codex/config.toml` | `~/.codex/clones/` |

探测顺序：

1. `SKILLBREW_RUNTIME=codex|claude`
2. Claude Code 相关环境变量
3. `CODEX_HOME`
4. `~/.codex`
5. 默认 Claude Code

也可以用全局参数覆盖：

```bash
skillbrew --runtime codex --mcp-json ~/.codex/config.toml --clones-dir ~/.codex/clones install <dir>
```

---

## 安全与礼貌的默认值

- 默认不写入：`install` 是 dry-run，`--approve` 才真实安装。
- 密钥不进仓库：`.env` 被 `.gitignore` 忽略，只提交 `.env.example`。
- 缓存只保存装法和变量名，不保存真实 secret 值。
- 缺 key、缺路径、缺运行时会标为 `needs_credentials` / `needs_config` / `needs_runtime`，不会假装 ready。
- 如果一个源不值得整装，`recommend` 会建议挑着装或整源跳过。

---

## 路线

当前最重要的改进方向：

1. 拆 `cli.py`，把命令入口拆成 `cli/commands/`。
2. 把 `install.py` / `installer.py` 归包，明确“安装执行层”和“装法推断层”。
3. 用结构化 schema 固定 `plan.json` / `install_list.json` / `dedup.json` / `recommend.json` 等中间产物。
4. 抽 `sources/` 输入源适配层，让新输入源只加 adapter。
5. 对接 MCP Marketplace，让 `skillbrew search` / `skillbrew info` / `skillbrew add` 成为通用入口。

详细决策见 [PROJECT_CHARTER.md](./PROJECT_CHARTER.md) 和 GitHub issues。

---

## 开发

```bash
pip install -e ".[dev]"
pytest -q
ruff check skillbrew/ tests/
mypy skillbrew/ --ignore-missing-imports --no-error-summary
python scripts/check_docs_sync.py --check
```

---

## 一句话

**SkillBREW 不是替你盲目安装更多东西，而是帮你把 Agent 能力从“看过、收藏过、装过但忘了”变成一套可验证、可回滚、可调用的本地资产。**
