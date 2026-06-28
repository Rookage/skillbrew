# SkillBREW — 技能酿造局

> **刷视频 → 收藏吃灰 → 重复装 → 越来越臃肿 → 装完不会调...**
>
> 技能酿造局：丢链接进去，**自动消化、自动评估、自动去重，真实安装后留下透明台账**，还能在 Claude Code 与 Codex CLI 之间**双运行时中立**运行。让你清楚 Agent 里有什么、怎么调。

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

## 六大核心能力

### 🧠 自动去重

把**本地已装能力**、**历史台账**和**新推荐**三者交叉比对，避免重复安装。

- 名字归一化命中 → 直接跳过
- 描述共享 ≥3 个有意义词 → 给出整并候选
- 其余 → 判定为新增
- 三层从严，只判「是否重复」，不黑盒决定「是否值得装」

### ⭐ 自动评估

`recommend` 判断步给每个候选能力打分，帮你决定：**值不值得装 / 挑着装 / 整源跳过**。

- 结合一手溯源结果（仓库存在性、星数、维护状态）
- 结合你已装的能力画像，标出重复/重叠
- 输出结构化建议，最终拍板权在人

### ⚡ 真实安装

不是只出计划，是**真正落盘**。

- 默认 **dry-run**，`--approve` 才真写
- 多形态支持：Skill / MCP / 代码 / 配置 / Prompt
- 按运行时约定落点（Claude Code / Codex CLI）
- 装完即能用，装错可回滚

| 形态 | 落地位置 | 安装方式 |
|------|---------|---------|
| Skill | `.claude/skills/<name>/` | 整目录拷贝（含 SKILL.md） |
| MCP | `~/.claude.json` 或 `.mcp.json` | `claude mcp add` 或 JSON 合并 |
| 代码 | 项目内模块 | 直接写入 |
| 配置 | `CLAUDE.md` 或片段库 | 追加或覆盖 |
| Prompt | 片段库或 Skill | 模板化存储 |

### 📊 透明台账

装完不是结束，是留下一张清楚的能力地图。

- **RECORD.md**：每次安装的来源、时间、调用方式、就绪状态（ready / needs_config 等）
- **DASHBOARD.md**：累计看板，一眼看清能力分布
- **去重/归并/可移除**：台账驱动，不会越装越乱
- **调用方式透明**：每个能力都标注怎么触发（`@skill` 名 / 触发提示词）

### 🤖 通用安装器（AI 推断）

不只是查人工目录，**AI 直接去源头仓库读 README 自己判断怎么装**。

四级降级链，每级失败都不崩：

1. **查本地缓存** — 以前验证过的装法，秒装
2. **查人工目录** — 6 条预验证种子（playwright / filesystem / sequential-thinking / context7 / github / sqlite）
3. **AI 读源头仓库推断** — 缓存/目录都没有时，拉仓库 README / package.json / pyproject.toml，推断装法和所需参数
4. **试跑验证** — 装前先跑 `--help` / `--version` 确认命令可用，最多重试 1–2 次换装法
5. **缺项补全** — 缺 key 弹窗问，缺路径让补，绝不静默崩

全走不通 → 老实标 `unresolved` + 写明卡在哪，不臆造、不黑箱。

```bash
# 默认关，加 --ai-infer 开启 AI 推断
skillbrew install data/sources/<id>/ --approve --ai-infer

# 跳过试跑验证（仅调试用）
skillbrew install data/sources/<id>/ --approve --ai-infer --no-trial

# 强制刷新本地缓存
skillbrew install data/sources/<id>/ --approve --ai-infer --refresh-cache
```

> **安全**：试跑只跑命令本身（`npx <pkg> --help`），绝不写真配置、不碰 `claude mcp add`。密钥只存变量名、不存值（D14）。验证过的装法记入本地缓存，下次秒装。

### 🖥️ 双运行时中立

不绑定某一个 Agent 运行时，**Claude Code / Codex CLI 都能跑**。

- 自动探测当前运行时
- 自动切换 Skill 目录、MCP 配置、克隆缓存路径
- 可用环境变量逐项覆盖，项目级 `.claude/skills/` 同样识别

**技术实现**：
- 文本理解：NVIDIA NIM 免费 Qwen3.5（快 50x，也支持 DeepSeek / Agnes）
- 视觉理解：同上 Qwen3.5（快 ~6s/张，文本+视觉同一模型）
- 字幕提取：yt-dlp + faster-whisper
- 关键帧抽取：ffmpeg + PIL 帧间差异签名

---

## 从混乱到清晰

```
刷视频 → 收藏吃灰 → 重复装 → 越来越臃肿 → 装完不会调
   ↓
SkillBREW 接管
   ↓
丢链接 → 自动消化 → 自动评估 → 去重判断 → 授权安装 → 台账记录
   ↓
清楚知道：装了哪些能力、几个 MCP 服务器、每个怎么调
（具体数字以本地台账为准，不硬编码）
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
| 7. 安装 | 去重决策 | 已装能力 | `install.py` + `installer.py` | `~/.claude/skills/` 或 `~/.claude.json`（`--ai-infer` 开启 AI 推断安装） |
| 8. 记录 | 安装结果 | 台账/看板 | `record.py` | `RECORD.md` + `DASHBOARD.md` |

---

## 现状

**骨架阶段，但已跑通端到端。**

- ✅ 8 步管线全通（B站 / 抖音双源验证）
- ✅ 多形态支持（Skill + MCP + 代码 / 配置 / Prompt + repo 克隆即用）
- ✅ 自动去重（三层从严 + 形态感知：Skill / MCP / repo 独立基准）
- ✅ 自动评估（`recommend` 三模式：keyword 规则打分 / manual 人工勾选 / ai 文本模型判断）
- ✅ 可视化报告（RECORD.md 台账 + DASHBOARD.md 看板 + INSTALLED_INDEX.md 能力索引）
- ✅ 授权门（默认 dry-run，`--approve` 才真装）
- ✅ 安装后 readiness 标注（透明标注 ready / needs_runtime / needs_config / needs_credentials）
- ✅ 双运行时中立（Claude Code / Codex CLI 自动识别，TOML/JSON 双格式 MCP 注册）
- ✅ 通用安装器（四级降级链：缓存→catalog→AI推断→试跑→缺项补全，AI 读源头仓库自己判断装法）
- ✅ 交互式配置引导（首次运行无 `.env` 时，有终端可逐项填入 key，无终端打印清晰指引）
- ✅ 结构化错误体系（`SkillbrewError` / `StepFailed` / `ConfigError` / `NetworkError`，中文报错含处理建议）
- ✅ 模型兼容层（自动按模型裁剪 `temperature`，避免 Claude 等严格模型 400 报错）
- ✅ CI 质量门（ruff lint + mypy 类型检查 + pytest 119 个测试全部通过）
- ✅ 新用户零配置体验（pip install 缺依赖不崩、--skip-asr 不阻断后续管线）

**已真装验证的 MCP 服务器：**

| 服务器 | 用途 | 状态 |
|--------|------|------|
| `@playwright/mcp` | 浏览器自动化（打开网页、点击、填表、检查报错） | ✅ 已装 |
| `@modelcontextprotocol/server-filesystem` | 文件系统访问（读写指定目录） | ✅ 已装 |
| `@modelcontextprotocol/server-sequential-thinking` | 结构化思考（复杂问题分步推理） | ✅ 已装 |
| `@upstash/context7-mcp` | 官方文档查询（查最新库文档） | ✅ 已装 |
| `@modelcontextprotocol/server-github` | GitHub 操作（issue / PR / 仓库查询） | ✅ 已装（已配置 PAT 并冒烟测试） |
| `zcaceres/fetch-mcp` | 网页抓取（把 URL 内容转成 markdown） | ✅ 已装（AI 推断安装，端到端验证通过） |

**以下能力因外部依赖或凭证未就绪，当前版本未默认安装：**

- Memos MCP：无官方 npm 包，候选 `@modelcontextprotocol/server-memory`，暂不安装
- MoneyPrinterTurbo：还缺 OPENAI_API_KEY，暂不配置

**技术栈：**

- 分角色配置（`.env`，已 gitignore）：文本组 `TEXT_*` / 视觉组 `VISION_*` 默认 NVIDIA NIM 免费 Qwen3.5，可换成 DeepSeek / Agnes
- 可插拔 LLM 客户端（D15）：`chat_text` / `chat_vision`，换供应商只改 `.env`
- 交互式配置引导：无 `.env` 时自动弹出问答，一步填完 key（D16/D21）
- 模型兼容层：自动按模型裁剪 `temperature` 等参数，换供应商零代码改动
- 自检命令 `skillbrew doctor`（含 ffmpeg 可用性检查）
- 结构化错误：中文报错 + 处理建议，Ctrl+C 不崩
- CI 质量门：ruff lint + mypy 类型检查 + pytest 119 测试全绿（含 installer 19 测试全覆盖）

---

## 安装

```bash
# 1. 复制配置并填入你自己的 key（也可以跳过——skillbrew 会在首次使用时交互式引导你填）
cp .env.example .env
#   编辑 .env：推荐 NVIDIA NIM 免费 Qwen3.5（快 50x），也支持 DeepSeek / Agnes
#   推荐替代：已改默认 NVIDIA，DeepSeek / Agnes 仍可用（见 .env.example 注释）

# 2. 系统依赖
#   必装：ffmpeg (Linux: apt install ffmpeg | Mac: brew install ffmpeg | Win: scoop install ffmpeg)

# 3. 安装（可编辑，注册 skillbrew 命令）
pip install -e .
```

依赖：`openai`、`numpy`、`Pillow`（必装，`pip install -e .` 自动安装）。视频获取 / ASR 走可选依赖 `pip install -e ".[media]"`（yt-dlp + faster-whisper，较大，按需装）。

---

## 运行环境中立（Claude Code / Codex CLI 双跑）

skillbrew 默认按所在运行时的约定找配置目录，不再写死 `~/.claude/*`：

| 运行时 | Skill 目录 | MCP 配置 | 克隆缓存 |
|--------|-----------|---------|---------|
| Claude Code | `~/.claude/skills/` | `~/.claude.json` | `~/.claude/clones/` |
| Codex CLI   | `~/.codex/skills/` | `~/.codex/config.toml` | `~/.codex/clones/` |

探测顺序：
1. `SKILLBREW_RUNTIME=codex|claude`（显式指定，最高优先级）
2. `CLAUDECODE=1` / `CLAUDE_CODE_SESSION_ID` / `CLAUDE_CODE_EXECPATH` → 判定为 Claude Code
3. `CODEX_HOME` 环境变量存在 → 判定为 Codex
4. `~/.codex` 目录存在 → 判定为 Codex
5. 否则默认 Claude Code

也可逐项覆盖路径：

| 环境变量 | 覆盖项 |
|---------|--------|
| `SKILLBREW_SKILLS_DIR` | Skill 安装目录 |
| `SKILLBREW_CLAUDE_JSON` | MCP 配置文件（Codex 下指向 `.codex/config.toml`） |
| `SKILLBREW_CLONES_DIR` | 仓库克隆缓存目录 |
| `SKILLBREW_CLAUDE_BIN` | `claude` 可执行文件路径 |

CLI 也提供对应的全局参数：

```bash
skillbrew --runtime codex --mcp-json ~/.codex/config.toml --clones-dir ~/.codex/clones install <dir>
```

> **注意**：Codex 使用 TOML 配置 MCP，当前 skillbrew 已返回正确的 Codex 默认路径，但 TOML 的读写尚未实现（仅 JSON）。在 Codex 下如需注册 MCP，请先通过 `SKILLBREW_CLAUDE_BIN` 提供 Claude CLI，或等后续版本补齐 TOML 支持。

项目级 `.claude/skills/` 检测保留：如果你在工作区里用项目级 Skill，无论哪个运行时都会优先识别。

## 快速开始

**示例：从抖音视频安装 6 个 MCP 服务器**

```bash
# 1. 采集 + 理解 + 消化（生成草稿计划）—— 一键跑完前三步
skillbrew run https://v.douyin.com/LcTwRFgJqas/
#   产物落在 data/sources/<自动id>/（下文以 douyin_7650401218518387995 为例）。
#   想分步：skillbrew ingest <url>（只采集）→ understand <dir> → plan <dir>。

# 2. 溯源 + 判断 + 去重（验证 + 评分 + 去重）
skillbrew verify data/sources/douyin_7650401218518387995/
skillbrew recommend data/sources/douyin_7650401218518387995/
skillbrew dedup data/sources/douyin_7650401218518387995/

# 3. 安装（默认 dry-run，看计划）
skillbrew install data/sources/douyin_7650401218518387995/

# 4. 确认无误，真装
skillbrew install data/sources/douyin_7650401218518387995/ --approve

# 4b. 开启 AI 推断（catalog 未收录的 MCP 也能装）
skillbrew install data/sources/douyin_7650401218518387995/ --approve --ai-infer

# 5. 生成台账 + 看板
skillbrew record data/sources/douyin_7650401218518387995/
```

每一步都可独立运行、可审计。中间产物在 `data/sources/<id>/` 下，随时可查。

---

## 自检

```bash
skillbrew doctor            # 配置 + 文本连通 + 视觉模型列表（快）
skillbrew doctor --vision   # 额外跑一次真·看图（NVIDIA ~6s/张，Agnes ~5min/张）
skillbrew config            # 打印解析后的配置（key 脱敏）
```

也可不安装直接跑：`PYTHONPATH=. python3 -m skillbrew doctor`。

---

## 首次运行须知

第一次跑 `understand` / `run`（带音频的视频）会踩几个坑，已自动处理：

**① ASR（语音转文字）模型首次下载**

- `understand` 用 faster-whisper（small/int8/CPU）转字幕，模型 `Systran/faster-whisper-small` 首次从 HuggingFace 下载（走镜像 `HF_ENDPOINT=https://hf-mirror.com`，国内友好），首次加载约 1～3 分钟。
- **下载失败不崩**：镜像/网络拉不下来时，skillbrew 会报错 + 跳出人类可读提醒（告诉你去哪下：`hf-mirror.com`，或翻墙走官方 `huggingface.co`，以及如何用本地模型），然后**降级跳过字幕**——关键帧看图照常，后续管线继续跑，只是消化质量打折（没字幕佐证）。
- **彻底离线兜底**：手动下好 `Systran/faster-whisper-small` 整个目录，在 `.env` 设 `WHISPER_MODEL_PATH=<那个目录>`，WhisperModel 直接加载本地路径，完全不触发网络下载。详见 `.env.example`。
- **纯文本输入**：`--skip-asr --skip-vision` 现在会自动补空字幕/视觉文件，不再崩溃——即使无 API key 也能先把素材采集下来。

**② Windows 终端 GBK 编码崩**

- 已**入口统一强制 UTF-8**（`errors=replace`）。极少数老环境若仍乱码：终端跑 `chcp 65001`，或设环境变量 `PYTHONUTF8=1`。

**③ 交互式 API key 配置（新增）**

- 首次运行 `skillbrew run` / `doctor` / `plan` 等步骤时，如果 `.env` 未配置，skillbrew 会**自动弹出交互式问答**，逐项引导你填入 API key。填完即写入 `.env`，下次不再问。
- 在无终端环境（headless / CI / 管道）中，skillbrew 打印清晰的配置指南并继续执行（不卡死）。
- 也可手动配置：`cp .env.example .env` → 编辑填入 key。默认推荐 NVIDIA NIM 免费 Qwen3.5。

**④ 邮件通知（可选）**

- 在 `.env` 填 `MAIL_ADDRESS` / `MAIL_AUTH_CODE` / `MAIL_PROVIDER`（预设 qq/163/gmail/outlook，或自定义 `MAIL_HOST`/`PORT`/`USE_SSL`），`install --approve` 真装完成会自动发一封 HTML 完成报告（清单 + 下一步待办）。
- 不配就不发、不报错（会在安装末尾提示一次「未配置」）。授权码不是登录密码，各供应商后台开 SMTP 拿。详见 `.env.example`。

---

## 配置说明

| 组 | 环境变量 | 默认供应商 | 用途 |
|----|---------|-----------|------|
| 文本 | `TEXT_BASE_URL` / `TEXT_API_KEY` / `TEXT_MODEL` | NVIDIA Qwen3.5（也支持 DeepSeek / Agnes） | 消化 / 执行计划 |
| 视觉 | `VISION_BASE_URL` / `VISION_API_KEY` / `VISION_MODEL` | 同上（文本+视觉同一模型） | 关键帧看图 |

**为什么分两组配置？**

- **文本组**：消化视频内容、生成执行计划、评分排序——推荐 NVIDIA NIM Qwen3.5（免费快 50x），也支持 DeepSeek
- **视觉组**：看关键帧截图、提取视频画面信息——同上 Qwen3.5（~6s/张，文本+视觉同一模型），旧推荐 Agnes (~5min/张) 保底可用
- **可插拔设计（D15）**：`chat_text` / `chat_vision` 两个函数封装，换供应商只改 `.env`，代码零改动

**为什么默认切到 NVIDIA Qwen3.5？**

2026-06-27 实测，NVIDIA NIM 免费 API 的新模型 `qwen/qwen3.5-122b-a10b` 看图速度快 50 倍（~6s/张 vs ~5min/张），且同一模型同时支持文本和视觉。中文原生好，API 格式 OpenAI 兼容。新账号送 ~5000 credits，无需绑卡。旧默认 Agnes（~5min/张）仍可用，改 `.env` 即可切回。

---

## 安全

**凭证保护**

- `.env` 已被 `.gitignore` 忽略（D14）。仓库只放 `.env.example` 占位（凭证留空）。
- 推 GitHub 前**无需重置 key**：脱敏靠 `.env` gitignore + 推后用 fresh-clone 零痕迹复扫（`grep` 真实 key 是否泄露进仓库）。key 留在本地 `.env` 不进仓库即可，换 key 反而打断本机在跑的流程。

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
  - github（needs_credentials：需 PAT 凭证）
  - ...
    ↓
用户确认？
  ├─ 否 → 结束，什么都不装
  └─ 是 → install --approve → 真装 → 记录台账
```

**安装后 readiness 标注**

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

---

**SkillBREW — 让 AI 能力从「信息过载」到「清楚知道」。**
