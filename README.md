# SkillBREW — 技能酿造局

[![CI](https://github.com/Rookage/skillbrew/actions/workflows/ci.yml/badge.svg)](https://github.com/Rookage/skillbrew/actions/workflows/ci.yml)
[![GitHub Pages](https://github.com/Rookage/skillbrew/actions/workflows/pages.yml/badge.svg)](https://github.com/Rookage/skillbrew/actions/workflows/pages.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](./pyproject.toml)
[![MCP](https://img.shields.io/badge/MCP-ready-8a63d2.svg)](#已验证的-mcp-种子--verified-mcp-seeds)

![SkillBREW hero](docs/assets/skillbrew-hero.png)

> **中文**：把散落在视频、网页、README 和推荐清单里的 Agent 能力，酿成可验证、可安装、可追踪的一套本地能力库。  
> **English**: Turn scattered agent tips from videos, webpages, READMEs, and tool lists into a verified, installable, trackable local capability cellar.

**SkillBREW** 是一个本地优先的 AI Agent 能力管理器。你丢进一个链接、视频或文档，它会采集内容、理解上下文、生成安装计划、回源验证、评估价值、检查重复项，并在你明确授权后把 Skill、MCP、代码片段或配置真实落地。安装完成后，它会留下台账和看板，让你知道自己到底装了什么、为什么装、以后怎么调用。

**SkillBREW** is a local-first capability manager for AI coding agents. Give it a link, video, webpage, or document; it collects the source, understands it, drafts an install plan, verifies upstream facts, scores the candidates, checks for duplicates, and only installs after you approve. Afterward it leaves a ledger, dashboard, and invocation notes so your agent toolbox becomes an asset instead of a junk drawer.

It is built for **Claude Code / Codex / MCP workflows**.

[GitHub Pages](https://rookage.github.io/skillbrew) · [Project Charter / 项目章程](./PROJECT_CHARTER.md) · [Contributing / 贡献指南](./CONTRIBUTING.md)

---

## 为什么需要它 / Why It Exists

很多 Agent 用户的能力库不是被设计出来的，而是被"顺手装一下"堆出来的：

Many agent workspaces are not designed. They are accumulated one "looks useful, install it" moment at a time:

- 刷到"必装 MCP"视频，先收藏，后来找不到。  
  You watch a "must-have MCPs" video, save it, and never find the trail again.
- 看到一个仓库很酷，复制安装命令，装完忘了怎么调用。  
  You copy a cool repo's install command, then forget what it does or how to call it.
- 同类工具装了三遍，名字不同，功能重叠。  
  You install the same kind of tool three times under three different names.
- 换 Claude Code / Codex 运行时后，路径、配置、MCP 注册方式又变了。  
  You switch between Claude Code and Codex, and suddenly paths, config files, and MCP registration rules change.
- 最后能力越来越多，但你不确定哪些可用、哪些缺 key、哪些只是躺在目录里。  
  The toolbox gets bigger, but not clearer: some tools are ready, some need keys, some are just sitting there.

**中文**：SkillBREW 解决的不是"下载一个工具"这么小的事，而是 **Agent 能力从信息过载到可管理资产** 的中间层。  
**English**: SkillBREW is not a fancier downloader. It is the missing layer between "I saw a useful capability somewhere" and "my agent can reliably use it."

---

## 它做什么 / What It Does

### 1. 从素材里提炼能力 / Distills capabilities from messy sources

输入可以是 B站、抖音、YouTube、网页或纯文本。SkillBREW 会把素材采集到本地，提取字幕、关键帧和正文，再让 LLM 消化成结构化计划。

Inputs can be Bilibili, Douyin, YouTube, webpages, or plain text. SkillBREW collects the material locally, extracts transcripts, keyframes, and page text, then asks an LLM to turn the mess into a structured plan.

### 2. 回到源头验证 / Checks the original source

视频里说"装这个 GitHub MCP 很好用"，它不会直接信。`verify` 会回源查仓库、README、包信息、维护状态和安装线索，尽量拿一手资料修正二手推荐。

If a video says "install this GitHub MCP," SkillBREW does not take that on faith. `verify` goes back to the repository, README, package metadata, maintenance signals, and install hints before turning a recommendation into an install candidate.

### 3. 先判断，再去重，再安装 / Scores first, deduplicates second, installs last

`recommend` 负责判断"值不值得装"，`dedup` 负责判断"是不是重复"。两件事分开做：不让 AI 黑箱决定，也不让你靠记忆硬扛。

`recommend` asks whether a capability is worth installing. `dedup` asks whether you already have something like it. Those are deliberately separate questions. The AI may advise, but it does not silently decide.

### 4. 授权后才真实落地 / Real writes happen only after approval

`install` 默认只 dry-run，显示计划；只有加 `--approve` 才会写入目录、配置或 MCP 注册文件。安装后再由 `record` 生成台账、看板和调用说明。

`install` defaults to dry-run. It shows what would happen. Only `--approve` writes skills, MCP config, repos, or snippets. Then `record` creates the ledger, dashboard, and usage notes.

### 5. 同时考虑 Claude Code 和 Codex / Built for more than one agent runtime

SkillBREW 已经有运行时识别层，可以按 Claude Code / Codex 的约定切换 Skill 目录、MCP 配置路径和 clone 缓存目录。它的目标不是绑死某一家 Agent，而是管理跨 Agent 的能力资产。

SkillBREW has a runtime-detection layer for Claude Code and Codex conventions: skill directories, MCP config paths, and clone caches. The goal is not to belong to one agent. The goal is to manage capabilities across agents.

---

## 8 步管线 / The 8-Step Pipeline

```text
采集 -> 理解 -> 消化 -> 溯源 -> 判断 -> 去重 -> 安装 -> 记录
Collect -> Understand -> Digest -> Verify -> Judge -> Deduplicate -> Install -> Record
```

| 步骤 / Step | 命令 / Command | 目的 / Purpose | 主要产物 / Output |
|---|---|---|---|
| 1. 采集 / Collect | `ingest` | 把 URL / 文本 / 网页素材落到本地 / Save source material locally | `metadata.json`、视频/音频/正文 |
| 2. 理解 / Understand | `understand` | ASR 字幕、关键帧、视觉描述 / Transcript, keyframes, vision notes | `transcript.txt`、`keyframe_visions.json` |
| 3. 消化 / Digest | `plan` | 把素材整理成可执行安装计划 / Draft an executable install plan | `plan.json` |
| 4. 溯源 / Verify | `verify` | 回源验证仓库、MCP、repo、可用性 / Check upstream facts | `install_list.json` |
| 5. 判断 / Judge | `recommend` | 评估值得装、挑着装、跳过 / Score and recommend | `recommend.json` |
| 6. 去重 / Deduplicate | `dedup` | 与本地目录和历史台账比对 / Compare with local installs and registry | `dedup.json` |
| 7. 安装 / Install | `install` | dry-run 或授权后真实落地 / Dry-run or approved writes | Skill / MCP / repo / config |
| 8. 记录 / Record | `record` | 生成能力台账和看板 / Generate ledger and dashboard | `RECORD.md`、`DASHBOARD.md` |

每一步都能单独跑。中间产物都留在 `data/sources/<id>/`，所以它不是不可审计的黑箱。

Each step can run on its own. Intermediate artifacts stay under `data/sources/<id>/`, so the pipeline is inspectable rather than mystical.

---

## 快速开始 / Quick Start

```bash
git clone https://github.com/Rookage/skillbrew.git
cd skillbrew

# Register the skillbrew command
pip install -e .

# Optional: video / ASR support, larger dependencies
pip install -e ".[media]"

# Check config; first run can guide you through .env setup
skillbrew doctor
```

跑一个素材 / Run a source:

```bash
# First three steps: collect -> understand -> digest
skillbrew run <url-or-text>

# Continue with verification, scoring, and deduplication
skillbrew verify data/sources/<id>/
skillbrew recommend data/sources/<id>/
skillbrew dedup data/sources/<id>/

# Preview the install plan; writes nothing
skillbrew install data/sources/<id>/

# Install for real after reviewing the plan
skillbrew install data/sources/<id>/ --approve

# Generate ledger and dashboard
skillbrew record data/sources/<id>/
```

日志与管道 / Logging and pipes:

```bash
# 默认：产品输出走 stdout，进度/诊断走 stderr，可直接管道
skillbrew recommend data/sources/<id>/ | jq .

# stdout 存结果、stderr 存日志
skillbrew install data/sources/<id>/ > result.json 2> install.log

# 开调试细节（第三方库日志会被压到 WARNING，不吵）
LOGLEVEL=DEBUG skillbrew verify data/sources/<id>/
```

通用 MCP 安装器实验能力 / Experimental universal MCP installer:

```bash
# If catalog has no entry, ask AI to infer the install method from upstream files,
# then trial-run before writing config.
skillbrew install data/sources/<id>/ --approve --ai-infer
```

---

## Current Limitations / 可信边界

SkillBREW 当前是 **骨架可跑通、核心链路已验证、仍在快速打磨的早期项目**。

SkillBREW is early: the skeleton runs, the core path is real, but the project is still being shaped in public.

已具备 / Already in place:

- 8 步管线端到端跑通。 / The 8-step pipeline runs end to end.
- B站、抖音、YouTube、网页、文本等输入源。 / Bilibili, Douyin, YouTube, webpages, and text sources.
- Skill / MCP / repo / 配置 / Prompt 等多形态安装计划。 / Multi-form install planning: Skill, MCP, repo, config, Prompt.
- 默认 dry-run，`--approve` 才写入。 / Dry-run by default; `--approve` writes.
- 本地扫描 + 台账扫描 + 形态感知去重。 / Local scan + registry scan + form-aware deduplication.
- `recommend` 支持 keyword / manual / ai 三种判断模式。 / `recommend` supports keyword, manual, and AI judging modes.
- 结构化错误提示，尽量避免裸异常。 / Structured errors instead of raw crashes where possible.
- Claude Code / Codex 运行时识别。 / Runtime detection for Claude Code and Codex.
- CI 覆盖 ruff、mypy、pytest 和文档同步检查。 / CI covers ruff, mypy, pytest, and docs-sync checks.

仍在打磨 / Still being improved:

- Codex 的 MCP TOML 写入仍在演进中，需要更多真实场景验证。  
  Codex MCP `config.toml` writing is evolving and needs more real-world round-trip tests.
- MCP Marketplace 对接还在 RFC 阶段。  
  MCP Marketplace integration is still in RFC stage.
- 单组件挑装（D20）尚未完全落地，当前多数 skill 仍按整目录拷贝。  
  Per-component selective install (D20) is not fully wired; most skills still copy whole directories.
- 中间产物的 schema 还在 dataclass 阶段，未固化成正式版本化协议。  
  Intermediate artifact schemas are still dataclass-level, not yet formalized as versioned contracts.

---

## 已验证的 MCP 种子 / Verified MCP Seeds

这些不是"全部生态"，而是当前作为 catalog / 缓存种子的预验证样本。

These are not the whole ecosystem. They are verified seeds used by the catalog/cache path.

| MCP | 用途 / Use | 状态 / Status |
|---|---|---|
| `@playwright/mcp` | 浏览器自动化 / Browser automation | 已验证 / Verified |
| `@modelcontextprotocol/server-filesystem` | 文件系统访问 / Filesystem access | 已验证 / Verified |
| `@modelcontextprotocol/server-sequential-thinking` | 结构化思考 / Structured reasoning | 已验证 / Verified |
| `@upstash/context7-mcp` | 官方文档查询 / Official docs lookup | 已验证 / Verified |
| `@modelcontextprotocol/server-github` | GitHub 操作 / GitHub operations | 已验证 / Verified |
| `zcaceres/fetch-mcp` | 网页抓取到 markdown / Fetch webpages into markdown | AI 推断安装验证通过 / AI-inferred install verified |

暂缓项 / Deferred:

- `memos MCP`：没有稳定官方 npm 包，暂不默认安装。  
  `memos MCP`: no stable official npm package yet; not installed by default.
- `MoneyPrinterTurbo`：需要额外凭证和运行环境，暂不默认配置。  
  `MoneyPrinterTurbo`: needs extra credentials and runtime setup; not configured by default.

---

## 架构地图 / Architecture Map

```text
                输入源 / Sources
    Bilibili / Douyin / YouTube / Webpage / Text
                       |
                       v
                CLI 层 / CLI Layer
           skillbrew <verb>  (cli/commands/*.py)
                       |
      ┌────────────────┼────────────────┐
      v                v                v
 doctor/config     run (8-step)     progress/spinner
(cli/commands/)   (pipeline flow)  (cli/utils.py)
                       |
                       v
                管线层 / Pipeline Layer
 ingest → understand → plan → verify → recommend → dedup → install → record
                                                                     |
                                                          install/ 子包
                                                    ┌──────┼──────┐
                                                    v      v      v
                                                  spec  resolver executor
                                                    |      |      |
                                                 catalog mcp_toml cache
                       |
                       v
                支撑层 / Supporting Layer
     config.py   llm.py   _logging.py   _utils.py
     registry.py   ratelimit.py   errors.py   notify.py
     mcp_catalog.py
```

几个关键模块 / Key modules:

- **CLI 层 / CLI layer:**
  - `cli/commands/`：每个管线步骤一个命令文件（ingest / understand / plan / verify / recommend / dedup / install / record / run / config / doctor）。/ One command file per pipeline step.
  - `cli/parser.py`：参数解析；`cli/utils.py`：spinner、进度条、终端辅助。/ Argument parsing; spinner, progress, terminal helpers.
- **管线层 / Pipeline layer:**
  - `ingest.py` / `understand.py` / `plan.py` / `verify.py` / `recommend.py` / `dedup.py` / `record.py`：对应 8 步里的 7 步。/ Seven of the eight pipeline steps (install lives under `install/`).
  - `install/` 子包：`spec.py`（InstallSpec 数据结构）、`resolver.py`（装法推断 + catalog + AI 推断）、`executor.py`（真实写入 + dry-run + MCP JSON/TOML 合并 + repo clone）、`mcp_toml.py`（Codex TOML 读写）、`utils.py`、缓存目录。/ Install subpackage: data model, method resolution + catalog + AI inference, actual writes + dry-run + MCP merge + clone, Codex TOML I/O, helpers, cache.
- **支撑层 / Supporting layer:**
  - `config.py`：运行时识别、路径约定、环境变量覆盖。 / Runtime detection, path conventions, environment overrides.
  - `llm.py`：OpenAI-compatible LLM 抽象，文本/视觉分离。 / OpenAI-compatible LLM abstraction with separate text and vision providers.
  - `_logging.py`：stdlib logging 配置；stdout 走产品输出，stderr 走诊断与 spinner。/ stdlib logging setup; product output on stdout, diagnostics and spinner on stderr.
  - `registry.py`：已装能力台账；`mcp_catalog.py`：已验证 MCP 种子；`ratelimit.py`、`errors.py`、`notify.py`、`_utils.py`：辅助件。/ Installed-registry ledger; verified MCP seeds; rate-limit, errors, notifications, shared helpers.

---

## 产物形态与落点 / Artifact Forms and Where They Land

| 形态 / Form | 落地路径 / Landing Path | 怎么调用 / How to Invoke |
|---|---|---|
| Skill | `~/.claude/skills/<name>/` 或 `~/.codex/skills/<name>/` | Agent 自动发现；斜杠命令或自然语言触发 |
| MCP 服务 / MCP server | 写入 `~/.claude.json`（Claude Code）或 `~/.codex/config.toml`（Codex）的 `mcpServers` | Agent 下次启动自动加载；工具名即调用入口 |
| Git 仓库 / Git repo | `~/.claude/clones/<repo>/` 或 `~/.codex/clones/<repo>/` | Agent 通过 Read/Grep/Bash 直接使用，或作为 skill 引用 |
| 配置片段 / Config fragment | 追加进项目 `CLAUDE.md` / `AGENTS.md`，或写入 `~/.claude/settings.json` | 下次对话自动加载为上下文/规则 |
| 提示词 / Prompt | 作为 skill 的 `SKILL.md` 一部分落地 | 触发 skill 时自动带入 |

安装后的台账和看板在 `data/ledger/RECORD.md` 和 `data/ledger/DASHBOARD.md`，记录了"装了什么、为什么装、怎么调"。

After install, the ledger and dashboard live at `data/ledger/RECORD.md` and `data/ledger/DASHBOARD.md`, recording what was installed, why, and how to invoke it.

---

## 配置 / Configuration

`.env.example` 提供两组模型配置 / `.env.example` provides two provider groups:

| 组 / Group | 变量 / Variables | 用途 / Purpose |
|---|---|---|
| 文本 / Text | `TEXT_BASE_URL` / `TEXT_API_KEY` / `TEXT_MODEL` | 消化、计划、判断 / digesting, planning, judging |
| 视觉 / Vision | `VISION_BASE_URL` / `VISION_API_KEY` / `VISION_MODEL` | 关键帧看图 / keyframe understanding |

默认推荐 NVIDIA NIM 的 Qwen3.5，因为它同时支持文本和视觉，OpenAI-compatible，中文表现好，速度也比旧视觉方案更适合本项目。你也可以换成 DeepSeek、Agnes 或其他兼容供应商。

NVIDIA NIM Qwen3.5 is the recommended default because it supports both text and vision through an OpenAI-compatible API, works well in Chinese, and is fast enough for this workflow. DeepSeek, Agnes, and other compatible providers can be swapped in via `.env`.

系统依赖 / System dependencies:

- `ffmpeg`：视频切帧、音频处理。 / Video frames and audio processing.
- `yt-dlp` / `faster-whisper`：安装 `.[media]` 后启用视频下载和 ASR。 / Enabled by `.[media]` for video download and ASR.

自检 / Self-check:

```bash
skillbrew doctor
skillbrew doctor --vision
skillbrew config
```

---

## 运行时中立 / Runtime Neutrality

| 运行时 / Runtime | Skill 目录 / Skill dir | MCP 配置 / MCP config | clone 缓存 / Clone cache |
|---|---|---|---|
| Claude Code | `~/.claude/skills/` | `~/.claude.json` | `~/.claude/clones/` |
| Codex | `~/.codex/skills/` | `~/.codex/config.toml` | `~/.codex/clones/` |

探测顺序 / Detection order:

1. `SKILLBREW_RUNTIME=codex|claude`
2. Claude Code environment variables
3. `CODEX_HOME`
4. `~/.codex`
5. default to Claude Code

也可以用全局参数覆盖 / Or override explicitly:

```bash
skillbrew --runtime codex --mcp-json ~/.codex/config.toml --clones-dir ~/.codex/clones install <dir>
```

---

## 安全与礼貌的默认值 / Safety Defaults

- 默认不写入：`install` 是 dry-run，`--approve` 才真实安装。  
  No writes by default: `install` is dry-run until `--approve`.
- 密钥不进仓库：`.env` 被 `.gitignore` 忽略，只提交 `.env.example`。  
  Secrets stay local: `.env` is ignored; only `.env.example` is committed.
- 缓存只保存装法和变量名，不保存真实 secret 值。  
  Cache stores install methods and variable names, not secret values.
- 缺 key、缺路径、缺运行时会标为 `needs_credentials` / `needs_config` / `needs_runtime`。  
  Missing keys, paths, or runtimes are marked as `needs_credentials`, `needs_config`, or `needs_runtime`.
- 如果一个源不值得整装，`recommend` 会建议挑着装或整源跳过。  
  If a source should not be installed wholesale, `recommend` can suggest selective install or source-level skip.

---

## 路线 / Roadmap

当前最重要的改进方向 / Current priorities:

1. **文档对齐**（进行中）：README、模块地图、产物形态表追上代码现实。/ Docs catch-up: refresh README, architecture map, and artifact table to match the shipped code.
2. **核心 schema 固化** (#24)：中间产物 dataclass 升级成版本化协议。/ Lock down versioned schemas for intermediate artifacts.
3. **输入源适配层** (#43)：抽 `sources/` adapter，bilibili/douyin/youtube/webpage/text/marketplace 统一接口。/ Extract a `sources/` adapter layer unifying all input types.
4. **MCP Marketplace 对接** (#27)：search/info/add 走通，复用 8 步管线。/ Integrate MCP Marketplace search/info/add, reusing the 8-step pipeline.
5. **按需补**：tomlkit (#40/#42)、文件锁 (#19)、类型补全——撞到再做，不排队。/ On-demand: tomlkit, file locking, type-annotation backfill — done when real bugs surface, not pre-emptively.

详细决策见 [PROJECT_CHARTER.md](./PROJECT_CHARTER.md) 和 GitHub issues。  
For deeper decisions, see [PROJECT_CHARTER.md](./PROJECT_CHARTER.md) and the GitHub issues.

---

## 开发 / Development

```bash
pip install -e ".[dev]"
pytest -q
ruff check skillbrew/ tests/
mypy skillbrew/ --ignore-missing-imports --no-error-summary
python scripts/check_docs_sync.py --check
```

---

## 一句话 / One Line

**中文**：SkillBREW 不是替你盲目安装更多东西，而是帮你把 Agent 能力从"看过、收藏过、装过但忘了"变成一套可验证、可回滚、可调用的本地资产。  
**English**: SkillBREW is not here to install more stuff blindly. It turns "I saw it, saved it, maybe installed it, then forgot it" into a verified, reversible, callable local capability system.
