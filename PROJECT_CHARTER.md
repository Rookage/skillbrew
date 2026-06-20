# 项目章程 PROJECT_CHARTER（核心锚定文件）

> 本文件是项目的"北极星"。每轮讨论后更新，所有开发以此为准，防止改着改着迷路。
> 状态：执行中 · 第 24 轮（2026-06-21） · B站单源 MVP **顺藤摸瓜到一手仓库并核实✅ + 授权A安装落地✅**（纠错：视频 OCR 的 `mattpockock/claude-skills` 错，真名 `mattpocock/skills`，⭐136,541〔2026-06-20 取数，星数动态非定值〕，全仓 34 个 skill）。产**三层分发文件**：`SKILL_PACK.md`（L1 机器 + L2 人读·可分享）+ `VIDEO_SCRIPT.md`（L3 口语化录像文案）。去重基准实扫纠正：工作区 **25 个 distinct**（pre-install）+ 用户级 1 个（`using-coze-cli`，与工作区重复→distinct 0）；**此前误记"31/0"已纠正**（刻舟求剑）。授权 A 已执行：15 净新增 + tdd 整并进 Python测试技能 → **25→40 distinct**（台账 active=40/merged=1）。**五步流①-⑤全部跑通 + 安装落地**；安装后报告 `POST_INSTALL.md` 已出。**r15：工具化前半段落地✅**——`run` 命令固化"丢链接→看视频→出草稿计划"，跑到草稿即停（刹车，不安装）。**r16：verify 溯源模块落地✅**——把"手动 curl GitHub 纠正 OCR 草稿"固化成 `verify` 子命令，纯 GitHub curl 不耗 LLM 配额，跑通即产机器安装清单 + 就地纠正 plan.json（星数 136,675〔2026-06-20 取数〕，open_questions 5/5 真回填）。**r17：dedup 去重模块落地✅**——把 D18"扫本地优先→再比台账"固化成 `dedup` 子命令，纯本地（磁盘 + 台账 SQLite）不调 LLM、不耗配额、不要 key；三层从严判定（名字命中→skip / 描述共享≥3 个有意义英文词→merge 候选 / 否则 new）。对 BV1UpR9BBEf5 跑通：基准 **41 个 distinct**（磁盘 41 + 台账 41 行 = active40/merged1，与手册已装集逐一对齐）→ 判定 **new=15 / merge=3 / skip=16**（16 skip 正是手册已装的 16 个 mattpocock skill；3 merge 均真·重叠方法论 skill——design-an-interface/improve-codebase-architecture→codebase-design、ubiquitous-language→domain-modeling，留待 install 授权时人工定夺）。初版阈值=2 偏松致 10 个假阳性 merge，收紧为 3 + 剔 skill/agent/file/issue/test 等泛词后纠回。**r18：install 安装模块落地✅（5 步第 4 步，授权门坐这）**——把"授权后整目录拷 + 登记台账"固化成 `install` 子命令：默认 dry-run、`--approve` 才真落盘 + 写台账；纯 GitHub raw + 标准库不调 LLM、不耗配额。修两 bug（install.py `db_path=None` 致 `connect` TypeError；verify.py tree-leak——`type=="tree"` 子目录节点混进 `files[]` 致 raw 404）。`--approve` 实测跑通：dedup new=15 去 2 deprecated → 实装 **13** 个新 skill，台账 **41→54 distinct**（active 40→53 / merged 1=tdd），会话 `before=41/added=13/after=54`。**"你落盘就是什么"核验✅**：磁盘 active distinct **53**（`~/.claude/skills` 14 + 工作区 40，同名重叠 `using-coze-cli` 1 → distinct 53）== 台账 active **53**；仅 `tdd`（merged，by design）台账有行无盘。本次 run 补足手动 run：16 skip + 13 new + 2 deprecated + 3 merge = 34 全仓，无重复安装。教训：dedup 扫**多目录**，磁盘-台账核对须覆盖全部扫描点（曾只查 `~/.claude/skills` 误报"40 行无盘"）

---

## 0. 一句话定位

一个 **"AI 能力包管理器"**：把视频/报告/文件丢进去，自动消化成"AI 可执行计划"，授权后按步安装成 AI 的真实能力（Skill/MCP/代码/配置），并维护一张可去重、可累加、可视化的能力台账。开源，本地优先。

## 1. 核心概念（术语统一）

| 术语 | 含义 |
|------|------|
| **素材 Source** | 输入的视频 / 报告 / 文件 / 网页（不止视频） |
| **消化 Digest** | 把素材转成结构化理解（含画面，非仅字幕） |
| **执行计划 Plan** | 消化后产出的"AI 可执行步骤清单"，每步可授权 |
| **能力产物 Artifact** | 计划落地后的实物：Skill / MCP / 代码 / 配置 / Prompt。形态由计划内容决定，不预设 |
| **能力台账 Registry** | 所有已安装能力的结构化登记表（去重/归并/分类/查询/移除） |
| **安装记录 Record** | 每次执行留一份 README 式可分享记录（装了什么、怎么装、可移除） |
| **看板 Dashboard** | 累加可视化（本次能力 + 历史归并后的整体能力） |
| **溯源 Verify** | 介绍到 GitHub/Anthropic/论文的素材，回原厂取一手资料，不只用二手 |

## 2. 痛点 → 目标

- **痛点**：用户每天收大量 AI 开发素材（视频/报告/文件），当"人肉编译器"消化不过来；喂给 AI 的还是二手、未落地。
- **目标**：去掉人工消化；素材 → 自动消化 → 可执行计划 → 授权安装 → 真实能力 + 累加看板；去重防臃肿；每次留可分享记录；开源共建。

## 3. 系统流程（精炼后）

```
① 采集   粘贴素材（视频URL / 文件 / 报告 / 网页）                 ← 多模态输入
② 理解   视频→字幕(ASR)+关键帧视觉融合；文件→直读；网页→抓取       ← 真正"看"视频
③ 消化   LLM 结构化理解 → 产出"执行计划"(分步、可授权)             ← 草稿即停(刹车)
④ 溯源   识别引用源头(GitHub/Anthropic/论文)→取一手资料、就地纠正草稿  ← 可选但推荐
⑤ 去重   扫本地已装 + 比台账 → 重复归并/升级，非新增              ← 只判"是否重复"(≠值得装)
⑥ 判断   给「值得装/不值得装/挑着装/整源跳过」主动建议 → 人定      ← 只判"是否值得装"(D19)
⑦ 审核   用户审计划+建议 → 通过 / 改 / 弃                         ← 交互门，绝不黑盒自动装(D22)
⑧ 安装   按步落地为能力产物(Skill/MCP/代码/配置) → 写入台账
⑨ 记录   生成 README 式安装记录(可分享、可回滚/移除)
⑩ 看板   本次能力 + 累加整体能力 → 可视化
```

## 4. 关键决策表

| # | 议题 | 决定 | 状态 |
|---|------|------|------|
| D1 | 部署形态 | 不用 Coze 工作流；引擎跑在可执行环境（当前云电脑），代码开源同步 GitHub | ✅已定 |
| D2 | 能力产物形态 | 综合型：先消化成计划，再决定产物(Skill/MCP/代码/配置) | ✅已定 |
| D3 | 首批素材源 | B站 → 抖音 → YouTube（国内优先，纵向先跑通） | ✅已定 |
| D4 | 视频理解路线 | 字幕(ASR) + 关键帧视觉融合，非纯转文字 | ✅已定（路线 + 依赖已核实并**实测**：Agnes-1.5-Flash 真看图——手搓左红右蓝图识别正确；⚠️单图~5min，见第10节问题5） |
| D5 | 质量把关 | 半自动：AI 生成计划草稿 + 用户一键审核 | ✅已定 |
| D6 | 溯源 | 介绍源头类素材回原厂取一手；整合类不强求 | ✅已定 |
| D7 | 防臃肿 | 台账去重 + 归并 + 可移除 + 每次留记录 | ✅已定 |
| D8 | 开源 | 放 GitHub 共建 | ✅已定 |
| D9 | （并入 D12） | — | — |
| D10 | 与 whale 关系 | 新建独立仓库；复用 whale 获取层"逻辑"（抖音反爬/ASR/ffmpeg 经验），不混仓库、不抄 Node 代码 | ✅已定 |
| D11 | 技术栈 | 纯 Python（MVP 只做 B站避开抖音反爬；抖音逻辑参考 whale 用 Python Playwright 重写） | ✅已定 |
| D12 | 项目名 | skillbrew（用户确认） | ✅已定 |
| D13 | 消化模型 | **分角色已拍板（2026-06-19）**：文本(消化/计划)=DeepSeek(deepseek-chat,1–2s,已充值)；视觉(关键帧看图)=Agnes(agnes-1.5-flash,已测真看图但~5min/张)。依据=DeepSeek 官方 API 视觉命门(发图被网关替换成 `[Unsupported Image]` 占位符、秒回,6/18 全量上线仅网页端≠官方 API)。.env 已拆 TEXT_*/VISION_* 两组独立配置(D15 可插拔,换供应商只改配置)。后续 DeepSeek 官方开放 API 视觉,改一行 VISION_* 即可切回 | ✅已定 |
| D14 | 安全脱敏 | 开源硬约束：密钥走 .env(git忽略)，代码只读环境变量，仓库只放 .env.example 占位；开发初期即埋入 | ✅已定 |
| D15 | LLM 客户端 | 模型无关(provider-agnostic)：统一抽象层，base_url+api_key+model 全走 .env 配置；换供应商只改配置不改代码 | ✅已定 |
| D16 | 开放给他人 | 须提供 API key 输入位(.env/配置/交互)，让用户填自己的 key；不绑死 Agnes/DeepSeek 任何供应商 | ✅已定 |
| D17 | 分发文件格式 | **三层结构（2026-06-20）**：① L1 机器可读结构化块(YAML，放文件顶部，任何 Agent 解析即能获取/安装/登记/去重)；② L2 人读·死板·规矩·可分享正文。L1+L2 打包成一个分享文件(`SKILL_PACK.md`)，类比 README(人) vs package.json(机器) 两者都要。L3 口语化录像文案**单独**给 UP 主念稿录视频用(`VIDEO_SCRIPT.md`)，不进分享包 | ✅已定 |
| D18 | 去重基准 | **基准 = 扫描本机已装 skill，每台机器/每个 Agent 不同（2026-06-20）**：全新机基准=0 直接加；成熟 Agent 已装很多→门槛高、逐项比对、重叠的去芜存菁/整并、不重叠的登记。两条推论：① 分享文件的去重指令**不可硬编码比对目标**（须写"先扫本地 .claude/skills/ 建基准再逐项比"）；② skillbrew 去重模块须**扫本地优先→再比台账** | ✅已定 |
| D19 | 判断先行·协助人类判断 | 用户盲目丢素材→skillbrew 先消化+判断，给「值得装/不值得装/挑着装/整源跳过」**主动建议**再让人定，绝不盲目整装；dedup 只判「是否重复」≠「是否值得装」须分开；对配置商店/大集合源主动建议挑着买或整源跳过+候选清单+跳过理由 | 🎯已定 |
| D20 | 安装粒度·挑着买 | 大集合/配置商店源**禁整目录盲拷**（r20 davila7 判「整目录装 832」即荒谬）；install 须支持「单组件选装/购物车组合/npx 一键装」，install_method 由源形态决定（非写死 copy_whole_dir）；能力/产物抽象见 D2+记忆 project-artifact-not-just-skill | 🎯方向已定 |
| D21 | 模型前置·文本必备·视觉可选优雅降级 | 使用本工具的**前置条件=至少 1 个大模型**（无 LLM 则消化步骤跑不动、工具完全不可用）；**任一品牌文本模型皆可**（所有 LLM 都有文字能力，不写死 DeepSeek）；**视觉模型为可选**——无视觉能力时**不卡死**，降级为「视频转语音→语音转文字」路径（识别质量较低、不能抽关键帧看画面），并主动建议换多模态模型但**不阻断**；配置=text_model(必填)+vision_model(可选)，契合 D15 热插拔/D16 开放他人；区别于 D13（D13=本机具体选型 DeepSeek+Agnes，D21=通用前置与降级规约） | 🎯已定 |
| D22 | 反盲盒·透明可追 | 直击「AI 全黑盒决定、人说好了但看不到、没安全感」的恐惧：① 消化素材后**必须**与人类交互确认才安装（强化 D19/D20 交互门，绝不黑盒自动装）；② 安装时说明每个功能**是什么**；③ 可视化报告须含「装了什么 / 新增哪些能力 / **以后怎么调用**」——尤其「调用方式」（@skill 名 / 触发提示词），让装了的能力能被找回、能被调用；呼应延后需求 R1（§9.1） | 🎯已定 |

## 5. 技术路线

### 5.1 输入获取
- **B站**：yt-dlp 取视频 + CC字幕；无字幕则下载音频 → ASR
- **抖音**：解析分享链接取直链下载；字幕少 → ASR
- **文件/报告**：直接读取（pdf/docx/md/html）
- **网页**：抓取正文

### 5.2 视频理解（关键 —— 回应"真正看视频"）
- **默认路线 = 字幕(ASR) + 关键帧视觉融合**
  - ASR(中文)：faster-whisper / funasr / whisper.cpp
  - 关键帧：~~ffmpeg 场景切换检测抽帧（`select='gt(scene,0.4)'`）~~【**r12 实测失效**：本 360p 短视频阈值 0.20 / 0.02 均抽出 0 帧，全程场景分极低】→ 改用 **PIL 帧间差异签名(32×24 灰度) + farthest-point 采样**：等距抽缩略图算灰度签名，贪心选互相差异最大的 N 帧(默认 5，限帧策略 A)、强制 min_spacing=5s 防扎堆。已落地 `understand.select_keyframes`
  - 视觉：关键帧 + 字幕一起送多模态 LLM（首选 Agnes-1.5-Flash；备选 Qwen-VL / Gemini / Claude）→ 看懂画面里的代码/图/UI/幻灯片
- **可选升级**：原生视频输入模型（Gemini 2.0 / Qwen-VL 直接吃视频）
- **纯字幕仅作降级方案**

### 5.3 溯源
- 从消化结果抽实体：GitHub repo / Anthropic 报告 / arXiv / 文档 URL
- 标注"一手溯源型" vs "二手整合型"
- **GitHub 一手取法（2026-06-20 实测，本环境）**：`gh` 未登录、无 GITHUB_TOKEN；WebFetch 对 `github.com` 被 claude.ai 安全策略挡。可通路径=**curl 直连 `api.github.com`**（同 B站 412 的绕过逻辑，直网可出）：① `/search/repositories?q=...` 搜仓库（**独立限速桶 10/min**，与核心 API 60/hr 不挤）；② `/repos/{owner}/{repo}` 核实存在+星数+默认分支；③ `/repos/{o}/{r}/git/trees/main?recursive=1` 拉全文件树（列全部 SKILL.md 路径）；④ **`raw.githubusercontent.com` 取静态文件不耗 API 限额**（拿 README / SKILL.md 正文用它最稳）。公开仓无需鉴权。r13 用此法核实 `mattpocock/skills`。
- **刻舟求剑方法论（r14 固化）**：溯源取回的任何**计数型元数据**（星数、skill 数、本地已装数）都是**动态线索、非永久事实**——星数日日涨、本地 skill 随装随删；把一个数字写进文档当定值 = 刻舟求剑。规矩：① 星数等动态值须标**取数时点**（`stars_observed_at`），仅作"顺藤摸瓜定位"用，勿当定值引用；② 本地已装数须**实时扫描**（D18），不可引用旧文档里的旧数；③ 发现旧文档数字与实测不符，就地纠正（"把错的资料变正确的"）。本机此条已践行：r13 误记"31/0"，r14 实扫纠正为 25 distinct + 1 重复。④ **验证须一手直查**（绝对路径 / 直接读盘），不可凭一次失败的探测就判定"不存在"——r14 收尾核验时，一次相对路径探针因 Bash 工作目录(CWD)不在工作区根而误报"`registry.db` 不存在"，险些据此推翻已真实落地的台账、去"纠正"本就正确的文档。教训：核验一律绝对路径直查；失败探针先复核根因（CWD / 路径拼写 / 权限）再采信，勿因一次探测失败就否定已落地事实。本机此条已践行：假警报经绝对路径直查解除，台账 active=40/merged=1 与磁盘 40 目录逐一核对一致。

### 5.4 能力产物落地
- 先生成"执行计划"（中间表示），再按内容选产物形态
- Skill → `.claude/skills/<name>/`
- MCP → `.mcp.json` 或 MCP 配置
- 代码 → 项目内模块
- 配置 / Prompt → CLAUDE.md 或片段库

## 6. 部署形态分析（Coze vs 本地）— 我的评估

**核心判断**：工具的目的是"让 AI 真实获得能力"，能力必须落到 **AI 运行时所在处**。
- Claude Code / Codex 运行在用户**本地** → 能力须落本地（`.claude/skills/` 等）
- Coze 云 Agent 跑在**云端沙箱** → 无法写用户本地任意路径（早前 PATH_OUTSIDE_WORKSPACE 已验证边界）

⇒ **落地点必须在本地**，这是硬约束。

**推荐**：本地 CLI 为核心引擎（消化/计划/安装/台账/看板全在本地，开源可克隆运行）；Coze 为可选门面（我现在跑的 Agent 可当"前台"：你把 URL 贴进对话，我编排消化、呈计划给你授权，再由本地引擎落地；Coze 也适合当看板查看器）。

**耦合度两档**：
- v1 松耦合：我在对话里给计划+产物，你本地手动跑安装（最简、最先开源）
- v2 紧耦合：本地引擎开 HTTP，Coze Agent 直接调（体验顺，但要本地常驻）

## 7. 架构（模块，初拟）

```
skillbrew/
  ingest/      采集 + 获取（各源 adapter；抖音反爬逻辑参考 whale，用 Python Playwright 重写）
  understand/  ASR + 关键帧 + 视觉融合
  verify/      溯源
  plan/        消化 → 执行计划
  install/     落地各形态产物
  registry/    能力台账（去重/归并/查询/移除）
  record/      安装记录（README 式，可分享）
  dashboard/   累加可视化
  cli/         命令入口
```

## 8. 框架 / 脚手架 / 依赖（初拟，待定）

- **语言**：纯 Python（生态最适合：yt-dlp / whisper / ffmpeg / PDF；单语言降门槛，避开混合栈 IPC 复杂度）
- **CLI**：Typer / Click
- **核心依赖**：yt-dlp, ffmpeg, faster-whisper/funasr, 多模态 LLM SDK
- **⚠️云电脑环境坑（已踩并解决）**：云电脑（非工作流 Python 沙箱）**可装软件、有 pip 权限**；但到 pypi.org 的链路慢，大依赖（如 onnxruntime 35MB）下载反复超时会 hang 死进程（曾导致安装"卡死"被强制终止）。**解法：pip 全局走阿里云镜像** `/etc/pip.conf` 已配 `index-url=mirrors.aliyun.com/pypi/simple/` + `timeout=60 retries=5`；后续装包默认走镜像。已装齐：yt-dlp 2026.06.09 / openai 2.43.0 / faster-whisper 1.2.1 / ffmpeg 4.4.2 / Python 3.13.12。
- **台账存储**：SQLite（轻、单文件、可查）
- **看板**：先 Markdown + Mermaid，后可选 Web
- **配置**：pyproject.toml

### 8.1 Agnes 接入速查（外部依赖，MVP 首选用）

- **注册**：https://platform.agnes-ai.com，邮箱注册，无需绑卡 / 手机号 / 实名
- **拿 key**：控制台 → API Keys → 创建新密钥 → 复制 `sk-` 开头 key（⚠️只显示一次，丢了只能重建）
- **接入参数**：base_url=`https://apihub.agnes-ai.com/v1`；走 OpenAI 兼容 SDK(openai 库)；认证 Bearer Token
- **模型分工**：agnes-2.0-flash = 字幕消化+执行计划(文本)；agnes-1.5-flash = 关键帧视觉(多模态，直接发 image_url，**无需任何开关**)
- **免费但有坑**：官方"核心模型无限期免费"、实测不扣 token；高峰期可能慢/排队；对 MVP(字幕+关键帧)影响小
- **可插拔**：换 DeepSeek / Qwen-VL / Gemini 只改 .env（D15），代码不动
- **诚实标注**：官方文档站(agnes-ai.com/doc)需 JS 渲染、coze web-fetch 抓不到正文，以上信息来自官方文档正文片段+多篇第三方教程交叉核实，注册控制台实际界面以你登录后看到的为准
- **实测结果（2026-06-19，真 key 冒烟测试 scripts/smoke_test.py）**：
  - ✅ key/base_url/auth 全通；`/v1/models` 返回 5 个确切 id：agnes-1.5-flash / agnes-2.0-flash / agnes-image-2.0-flash / agnes-image-2.1-flash / agnes-video-v2.0
  - ✅ 文本 agnes-2.0-flash：7.5s，自报"由 Sapiens AI 开发的 Agnes-2.0-Flash"
  - ✅ 视觉 agnes-1.5-flash：**真看图**——手搓「左红右蓝」PNG，正确答出"红色和蓝色分别位于图像左右两侧"
  - ⚠️ 视觉单图耗时 298.9s(~5min)，"慢也是真的"被实测坐实；批量关键帧须限帧+后台异步（见第10节问题5）。**两次实测稳定:244.6s / 298.9s,文本 1.3–7.5s,慢是稳定现象非偶发**

## 9. 预计达成目标（里程碑，纵向先跑通）

- **MVP**：B站单源 → 字幕+关键帧消化 → 执行计划 → 人工审 → 装 1 个 Skill → 台账 + 单次报告。**目标：证明闭环跑通**。
- **v1**：+抖音 +溯源 +去重归并 +累加看板 +安装记录/可移除 +多形态产物
- **v2**：+YouTube +Coze 门面 +GitHub 开源包装 +分享

### 9.1 延后需求（记录待后续版本，不进 MVP）

- **R1 能力调度/自动加载器（v2+）**：用户痛点（2026-06-20 提出）——skill 装了一堆但 Agent 不会自动调用，须 `@skill` 或读其 prompt 才触发，否则装 1000 个也不调。这是与「安装」正交的另一层：**调度器**（任务执行前扫自己已装能力→判该加载哪些→加载→再执行），非 skillbrew 安装器的职责。MVP 桥接：报告/台账带「调用方式」（@名/触发提示词，见 D22）让人工/Agent 能手动调；完整自动调度留 v2+ 独立组件。MVP 不实现。

## 10. 本轮开放问题（待确认）

1. ~~D1 部署~~ ✅已定（不用 Coze 工作流；引擎跑可执行环境，代码同步 GitHub）
2. ~~MVP 范围~~ ✅已定（B站单源 + 跑通闭环）
3. ~~项目名~~ ✅已定（skillbrew）
4. ~~D4 依赖~~ ✅已核实：yt-dlp+faster-whisper 装机中；视觉模型走 Agnes-1.5-Flash(已确认支持图像输入/识图/OCR/图表分析)，经 D15 可插拔；Claude 仅作硬兜底。
5. **⚠️Agnes 视觉单图~5min(实测稳定244–299s)——批量关键帧会过慢。限帧策略✅已定(用户拍板 A+B+C 全要)**：
   - 方案A 限帧：每视频只抽 3–8 张场景切换最剧烈的关键帧(非几十张)，太密集没必要
   - 方案B 并发：多帧同时请求提速；**须先查 Agnes 官方限速(每分/每秒多少请求)，在限额内用**
   - 方案C 选择性：仅字幕说不清的画面(代码/图表/UI/幻灯片)才送视觉，纯口播帧跳过——更智能
   - 执行顺序：先 A+C 跑通闭环；B 等查清 Agnes 限速再加

6. **模型供应商——✅已拍板分角色（2026-06-19）**：文本=DeepSeek、视觉=Agnes（依据=D13 + 下方命门实测）。.env 已拆 TEXT_*/VISION_* 两组独立配置，skillbrew 骨架开建。
   - **DeepSeek 视觉（实测命门，2026-06-19，真 key 冒烟测）**：官方 API **不支持视觉**。OpenAI 端点(`/v1/chat/completions` + `image_url`)直接报 400 "unknown variant image_url, expected text"；Anthropic 兼容端点(`/anthropic/v1/messages` + Anthropic 图片块)虽返回 200，但模型称看不到图、并直指网关把图替换成了 **`[Unsupported Image]` 占位符**；base64 与公网 URL 两种传图方式结果一致、且秒回（真看图会慢）。结论：**6/18 全量上线的是网页端「识图模式」，官方 API 尚未开放视觉**。第三方中转(napiai.com)能跑通是中转层另走通道，非官方 API。
   - **DeepSeek 文本（实测可用）**：deepseek-chat 1–2s、自报"由深度求索创造的 DeepSeek"，已充值。字幕消化+执行计划用 DeepSeek 文本完全胜任。
   - **Coze 尊享版**（上轮已查清，维持）：Bot 中心、无原生模型 API、不适配 D15，且与 D16 冲突 → MVP 不考虑（用户已拍板"先不开枝散叶"）。
   - **✅已拍板（2026-06-19，用户："好的，都按照你的计划，我们来执行"）**：**分角色**——文本(消化/计划)=DeepSeek（快、便宜、已充值）；视觉(关键帧看图)=Agnes（唯一已测真看图的官方 API）。这正是 D15 可插拔设计的价值：不同环节各取所长，不赌单一供应商。.env 已拆成 TEXT_*/VISION_* 两组独立配置（DeepSeek 与 Agnes 的 base_url+key 不同，已落地）。Agnes 视觉~5min/张的慢，靠已定的限帧 A+C 缓解。后续 DeepSeek 一旦开放官方 API 视觉，改一行 VISION_* 即可切回。

## 11. 修订记录

- **2026-06-21 r24**：**§3 系统流程图纠偏**。原图 9 步缺 `recommend`（判断步）、且把「去重」画在「安装」之后，与实现脱节。按实际闭环 `ingest→understand→plan→verify→dedup→recommend→install→record` 重排为 10 步：①采集 ②理解 ③消化 ④溯源 ⑤去重 ⑥判断(recommend) ⑦审核 ⑧安装 ⑨记录 ⑩看板。关键修正：去重(⑤)与判断(⑥)均在安装(⑧)之前；标注 dedup 只判"是否重复"≠recommend 只判"是否值得装"(D19)、审核为交互门绝不黑盒自动装(D22)；「溯源」从消化前移到消化后，对齐 r15-r16 实现（plan 出草稿→verify 就地纠正）。**纯文档纠偏，未改任何决策、未改代码**。

- **2026-06-21 r23**：**skillbrew 上 GitHub 私有仓库 + 全量脱敏复扫通过 + 立「不换 key」规则**。① **推送**：`github.com/Rookage/skillbrew`（PRIVATE），仅代码+文档，`data/` 不传（含 B站真 cookie/本机绝对路径/视频素材，`.gitignore` 整目录排除）；2 个 commit（initial + 脱敏修正）。② **脱敏三关**：(a) 两把真 key（DeepSeek/Agnes）零痕迹；(b) B站 cookie 靠 data/ 整排解决；(c) 本机路径（registry.db 54 条 `/root/.coze`）靠 data/ 整排 + HANDOFF.md/`scripts/register_install_a.py` 硬编码路径改通用（`~/.claude/skills`/`<workspace>/.claude/skills`/`ROOT.parent.parent/.claude/skills`）。③ **GitHub 端 fresh-clone 复扫**：远端最新 commit clone 到 /tmp，全维度扫 28 文件 → **干净 28/28 | 警报 0/28 ✅**（维度=两把真 key 完全+指纹、sk-token≥20、ghp_/gh[posr]_/github_pat_、Bearer、AWS AKIA、Slack xox、B站 cookie、本机路径/agent_id）。④ **立新规（用户最高优先级「不想换 API key」，覆盖 §8 旧规与旧记忆「推前重生成 key」）**：脱敏 = `.env` gitignore + 提交零痕迹 + fresh-clone 复扫，**不靠换 key**；两把真 key 永不进仓库、永不轮换。⑤ 凭据卫生：GitHub PAT 临时登录、用后即焚（shred 临时文件 + 删 `~/.config/gh/hosts.yml` + remote URL 确认无 token）；用户应去 GitHub 撤销该 PAT。⑥ 四档案同步：HANDOFF.md（顶部新增节 + §8 重写）、git-staged-checkpoint.md（整篇重写）、skillbrew-step5-handoff.md（3 处）、MEMORY.md（2 行索引）。**下一步待用户确认**：全量 ai 判断跑（~84 次 DeepSeek 调用）/ R1 调度器（v2+）。**未改任何已定决策**。

- **2026-06-20 r22**：**用户提 2 条新决策 D21（模型前置）+ D22（反盲盒）+ 1 条延后需求 R1（能力调度器）**，均不改已定决策、仅新增。① **D21 模型前置·文本必备·视觉可选优雅降级**——用户发现逻辑 bug：要跑本工具须两种 LLM 能力（文本+图片识别），若用户无 DeepSeek/Agnes 是否整个动不了？定性为：**前置条件=至少 1 个大模型**（无 LLM 则消化步骤跑不动、工具完全不可用）；**任一品牌文本模型皆可**（所有 LLM 都有文字能力，不写死 DeepSeek，契合 D15/D16 通用化）；**视觉为可选**——无视觉能力时**不卡死**，降级「视频转语音→语音转文字」路径（识别质量较低、不能抽关键帧看画面），主动建议换多模态模型但**不阻断**；配置=text_model(必填)+vision_model(可选)。区别于 D13（D13=本机具体选型 DeepSeek+Agnes，D21=通用前置与降级规约）。② **D22 反盲盒·透明可追**——直击「AI 全黑盒决定、人说好了但看不到、没安全感」的恐惧：① 消化素材后**必须**与人类交互确认才安装（强化 D19/D20 交互门，绝不黑盒自动装）；② 安装时说明每个功能**是什么**；③ 可视化报告须含「装了什么 / 新增哪些能力 / **以后怎么调用**」——尤其「调用方式」（@skill 名 / 触发提示词），让装了的能力能被找回、能被调用。③ **R1 延后需求（v2+，新增 §9.1）**——用户痛点：skill 装了一堆但 Agent 不会自动调用，须 `@skill` 或读其 prompt 才触发，否则装 1000 个也不调。定性为与「安装」正交的另一层「调度器」（执行前扫已装能力→判该加载哪些→加载→执行），非 skillbrew 安装器职责；MVP 仅靠 D22 报告带「调用方式」让人工/Agent 手动调，完整自动调度留 v2+ 独立组件。**下一步仍待用户确认**：recommend 判断步架构（我已提案 5 点：recommend 3 模式可切 ai/keyword/manual / 安装建议清单+交互菜单 / 复用 dedup 扫描出本机能力画像 / 看板新状态+finding-2 折入 / doctor 自检），用户尚未回「顺我就开写」。**未改任何已定决策**。

- **2026-06-20 r21**：**用户拍板两条新决策 D19（判断先行）+ D20（挑着买）**，源自 r20 davila7 源判断实战。① **D19 判断先行·协助人类判断**：固化「用户盲目丢素材 → skillbrew 先消化+判断 → 给『值得装/不值得装/挑着装/整源跳过』主动建议 → 人定」为制式规范（替代用户人肉看视频判断有用才执行的行为）；**dedup 只判「是否重复」≠「是否值得装」须分开**（DASHBOARD §6「代码去重只判是否重复、不判是否值得装」诚实注升级为主动建议）。② **D20 安装粒度·挑着买**：大集合/配置商店源禁整目录盲拷（r20 davila7 判「整目录装 832 个」即荒谬），install 须支持单组件选装/购物车组合/npx 一键装，install_method 由源形态决定（非写死 copy_whole_dir）。③ **对 BV1Kj9zBWEjS 给出数据驱动建议：整源跳过安装**——870 中 scientific 139 + ai-research 框架类 ~130 均学术/科研数据库非用户方向；~50+ SaaS 工作流（notion/slack/jira/linear/railway/pocketbase/sentry/neon/supabase/vercel/stripe/shopify/figma/telegram/discord）用户在 Coze 中文平台+金山文档/企业微信用不上；余者多与已有 skill 重叠（code-review*/security-*↔review/security-review、deep-research↔deep-research、docx↔docx、database-*↔数据库模式设计、obsidian-*↔obsidian-vault、writing-skills↔writing-beats/fragments/shape、development↔engineering-*）；**唯一值得当参考（非安装）的是 skill-authoring 元技能簇**——skill-creator/skill-developer/skill-judge/writing-skills + cc-skill-coding-standards/cc-skill-continuous-learning/cc-skill-strategic-compact/cc-skill-security-review + template-skill，因用户正在造 skill 管理器（skillbrew），这些是「别人怎么造/评 skill」的一手经验，可喂给「值不值得装」判断逻辑。④ **该源真实价值=架构案例**（逼出 D19/D20），非技能来源。⑤ **Coze 会员 API 模型调用舍弃**（用户定——太复杂、无法成为公开代码的一部分，关闭 D15 项下 dormant 的 Coze 3.0 API 问题）。⑥ **下一步设计待用户确认分叉**：`recommend` 判断步用 LLM 还是启发式？「用户方向/已有能力」如何作为输入（用户画像）？选装 UI/cart 语义？确认后实现。**未改任何已定决策**，仅新增 D19/D20。

- **2026-06-20 r19**：**record + 看板 代码生成落地✅（5 步计划第 5 步）**。把"安装记录 + 累计看板"从**手写 Markdown** 变成**代码生成**，完全从一手数据（`registry.db` / `dedup.json` / `install_list.json` / `plan.json`）驱动，**不许手写死任何数字**（刻舟求剑 §5.3——星数/计数皆线索非事实，会变；写死即过时）。① **`skillbrew/record.py` 数据驱动改造**：新增 3 个辅助函数——`_session_label(i, choice)`（→`①手动 A`/`②代码 --approve`）、`_session_arrows(sessions)`（一行文字累加轨迹）、`_cumulative_flow(sessions, active, merged)`（before/added/merged/after 累加 Mermaid，**全从 `install_sessions` 现取**，末节点附 `{active} active+{merged} merged` 细分），替换掉 RECORD §5 / DASHBOARD §0/§1/§4 里写死的 `25/40/54`。② **`_gather()` 加读 `plan.json`**：提取 `ocr_note`（`traced_sources[0].note` 整段纠错叙事）、`verify_how`、`verify_corrections`——OCR 误记的具体错值（错仓库名 `mattpockock/claude-skills`、错星数 `81.6k`）**只存在于 note 自然语言、无结构化字段**，走**方案A**：正文整段引用 `g["ocr_note"]`（含错值+纠正值+取数时点），Mermaid「OCR 误记」节点用 `g["verify_corrections"][0]` 描述文本（"OCR 错误仓库名/星数 → 一手核实纠正"），**不写死具体错值**——彻底数据驱动、不解析自然语言（方案B 正则提脆弱，否决）。③ **`skill_dirs` 口径 bug 修复**：record 默认改读 `dedup.json` 的 `baseline.skill_dirs`（与去重基准同口径，扫 `~/.claude/skills` + 工作区 `.claude/skills` 两个目录），避免只扫单目录致虚假「孤儿/缺失」（r18 教训：曾只查 14 个 vs 台账 54 行误报）。④ **CLI 加 `record` 子命令**：`python -m skillbrew record <源目录/BV/URL> [--skills-dir DIR]`；`--skills-dir` 为**追加**语义（因 `record.record()` 传 list 是**替换**非追加，CLI 须预合并 `dedup 默认目录 + 追加目录` 再传，否则漏扫）；`_resolve_source` 处理 BV→源目录（修掉 bare 模块 `_main` 不解析 BV、只认全路径的坑）。⑤ **刹车设计（D18/刹车）**：`record` **只读**——不调 LLM、不下载、不改台账，`on_progress` 仅 read/write 两阶段通报；产 `RECORD.md`（安装台账记录）+ `DASHBOARD.md`（累计看板）两份代码生成产物。⑥ **诚实注保留**（刻舟求剑 §5.3 + 设计决策 §5.3）：RECORD §2 两次会话 before/after **口径差异**注（会话1 手动 A 按 active 计 after=40；会话2 代码 `--approve` 按 distinct 计 before=41/after=54；最终统一 distinct=54=active53+merged1）+ DASHBOARD §6「代码去重只判是否重复、**不判是否值得装**」——两处诚实点改造时保留，措辞数据驱动化但不删。⑦ **产物形态抽象**（记忆 `project-artifact-not-just-skill`）：看板/记录用「能力/产物」抽象，不写死「skill」字样——MVP 样例 BV1UpR9BBEf5 装的是 skill 纯属顺手（该视频恰是方法论打包成 skill），不代表工具只管装 skill；台账 `form` 字段预留 skill/MCP/Code/Config/Prompt/操作步骤多形态。⑧ **实测 `python -m skillbrew record BV1UpR9BBEf5` 跑通✅**：本源 2 次会话、本次新装 13、落盘核对磁盘 active distinct **53** == 台账 active **53**（孤儿 0 / 缺失 0）；**grep 验证 `record.py` 零硬编码字面量**（`81.6k`/`mattpockock`/`25 distinct`/`40 active`/`54 distinct`/`BV1UpR9BBEf5` 全 0 命中——数字 25/40/54 出现在产物里是因它们是 `install_sessions` 实时值，非代码常量）；生成产物中 `81.6k` 缺席、`mattpockock/claude-skills` 仅经 `ocr_note` 引用在 DASHBOARD §1 出现一次（非 Mermaid 节点）。⑨ **5 步可复用工具计划（D18）至此全部落地**：r15 run ✅ → r16 verify ✅ → r17 dedup ✅ → r18 install+registry ✅ → **r19 record+看板 ✅** → r20 回归测试。**未改任何已定决策**。

- **2026-06-20 r18**：**install 安装模块落地✅（5 步计划第 4 步）**。把"授权后整目录拷 + 登记台账"固化成可复用 CLI，回应"授权 A 安装落地"的工具化——本轮用户"怎么没有执行呢？"即授权进 install。① **新增 `skillbrew/install.py`**（~230 行，纯标准库 urllib + GitHub raw，不调 LLM、不耗 DeepSeek/Agnes 配额、不要 key）：读 `install_list.json` + `dedup.json` → 挑 dedup 判 `new` 的整目录从 raw 拷到 `~/.claude/skills/<name>/` → `upsert` 台账 → 记安装会话。② **刹车设计（D18/刹车）**：`install` 默认 **dry-run**（只列计划 to_install/skipped_*，不下载不写台账），`--approve` 才真落盘 + 写台账——授权门就坐在这。③ **装哪些规则**：`new`→装（整目录拷：每个 skill = 目录下全部文件）/ `merge`→不自动装（人工确认候选，标出留后）/ `skip`→不装（已装/已整并）/ `new` 里 `category=deprecated`→默认跳过（`--include-deprecated` 才装）。④ **路径安全 + 重试**：`_rel_within` 防路径穿越（拒绝对绝对路径与 `..`，把仓库 file_path 转成 skill 目录内相对路径）；`_fetch_bytes` 对 5xx/网络瞬时错误退避重试（`_MAX_RETRIES=3`/`_RETRY_BACKOFF=2.0`，同 verify._get）；整目录拷完才 upsert 该 skill（部分安装可安全重跑：文件覆盖同内容、台账 upsert 幂等）。⑤ **CLI 加 `install` 子命令**：`python -m skillbrew install <源目录/BV/URL> [--approve] [--include-deprecated] [--target-dir DIR]`，dry-run 打印计划+跳过项，`--approve` 打印已装清单（名/文件数/路径）+ after 计数。⑥ **两个 bug 修复**：(a) `install.py` 传 `db_path=None` 致 `registry.connect(None)` 把默认 `DB_PATH` 盖掉报 TypeError —— 改 `registry.connect(db_path if db_path is not None else registry.DB_PATH)`；(b) **verify.py tree-leak**——`group_skill_dirs` 第二遍把 `type=="tree"`（子目录）节点也收进 `files[]`，致其 `raw_url` 404、install 中断；加 `if t.get("type") != "blob": continue` 只收文件（git/trees 端点 type 字段 = blob 文件 / tree 子目录 / commit 子模块）。⑦ **实测 `--approve` 跑通**：dedup 判 new=15，其中 2 个 `category=deprecated`（qa、request-refactor-plan）默认跳过 → **实装 13 个**新 skill 到 `~/.claude/skills/`，整目录拷（git-guardrails-claude-code 2 文件、setup-matt-pocock-skills 6 文件、余各 1 文件，SKILL.md 均在）；台账 **41→54 distinct**（active 40→53、merged 1 不变=tdd）；安装会话行 `before=41/added=13/merged=0/after=54`、`authorization_choice=install --approve`。⑧ **"你落盘就是什么"核验✅**：磁盘 active distinct **53**（`~/.claude/skills` 14 + 工作区 `.claude/skills` 40，同名重叠 1=`using-coze-cli`→distinct 53）== 台账 active **53**；仅 `tdd`（merged，并入 Python测试技能，by design）台账有行无盘；本次 run 补足手动 run：16 skip（手动已装）+ 13 new（本次）+ 2 deprecated + 3 merge = 34 全仓，无重复安装。⑨ **教训记入**：dedup 扫**多个**目录，磁盘-台账核对须覆盖全部扫描点（曾只查 `~/.claude/skills` 14 个 vs 台账 54 行误报"40 行无盘"——漏了工作区那 40 个）。**未改任何已定决策**。

- **2026-06-20 r17**：**dedup 去重模块落地✅（5 步计划第 3 步）**。把 D18"扫本地优先→再比台账"固化成可复用 CLI，回应"防臃肿去重"——装之前先判这批哪些是真新、哪些已装/可整并。① **新增 `skillbrew/dedup.py`**（纯本地：扫磁盘已装 skill 目录 + 读台账 SQLite，不调 LLM、不耗 DeepSeek/Agnes 配额、不要 key）：默认扫 `~/.claude/skills`，`--skills-dir` 可追加工作区等目录（D18 每台机器/每个 Agent 已装集不同，故扫本地优先、不硬编码比对目标）。② **三层从严判定**：名字归一化命中（grill-me==GrillMe）→ `skip`；描述共享 ≥3 个有意义英文词（剔 skill/agent/file/issue/test 等泛词）→ `merge` 候选（人工确认，不自动整并）；否则 → `new`。③ **基准 = 扫本地已装集**：对 BV1UpR9BBEf5 跑通，基准 **41 个 distinct**（磁盘 41 + 台账 41 行 = active40/merged1，与手册已装集逐一对齐）→ 判定 **new=15 / merge=3 / skip=16**（16 skip 正是手册已装的 16 个 mattpocock skill；3 merge 均真·重叠方法论 skill——design-an-interface、improve-codebase-architecture→codebase-design、ubiquitous-language→domain-modeling，留待 install 授权时人工定夺）。④ **阈值纠错**：初版共享词阈值=2 偏松，致 10 个假阳性 merge；收紧为 3 + 剔泛词后纠回真·3 个。⑤ **CLI 加 `dedup` 子命令**：`python -m skillbrew dedup <源目录/BV/URL> [--skills-dir DIR]`，结尾打印基准+判定+merge 候选+刹车提示（到此只判定+出报告，未安装）。⑥ 产 `dedup.json`（baseline 含扫描目录/计数/状态分布 + decisions 每项 name/category/decision/target/shared）。**未改任何已定决策**。

- **2026-06-20 r16**：**verify 溯源模块落地✅（5 步计划第 2 步）**。把 r13"手动 curl GitHub 纠正 OCR 草稿"固化成可复用 CLI，回应"承重墙须把模糊 OCR 猜测纠正为真正可安装"。① **新增 `skillbrew/verify.py`**（~500 行，纯标准库 urllib，不调 LLM、不耗 DeepSeek/Agnes 配额、不要 key）：三条 GitHub 取数路径——`/repos/{o}/{r}` 核实存在+星数+默认分支、`git/trees/{branch}?recursive=1` 拉全文件树、`raw.githubusercontent.com` 取 SKILL.md 正文（raw 不耗 API 限额，路径必用完整树路径）。② **仓库名从"错草稿"找回"真身"（不硬编码）**：直查草稿 repo（多半 404）→ 拿草稿 repo 名当种子 GitHub 搜仓库按星排+体积升序逐个拉树 → 校验"候选树含草稿点名 skill（grill-me/tdd）"才命中（一手内容校验，防搜到同名高分但内容不符的仓库）→ 全不命中报错让 `--repo` 指定。③ **一个 skill = 整个目录**：`group_skill_dirs` 把树里所有 SKILL.md 按目录归组（支持 `skills/<category>/<name>/SKILL.md` 与平铺），多文件 skill（tdd 4 文件）记目录树路径+全部文件，install 时整目录拷。④ **产 `install_list.json`**（机器可执行安装清单：verified_repo+星数+stars_observed_at+每个 skill 的 dir_path/files/raw_url）+ **就地回填纠正 plan.json**（`backfill_plan` 改 source_title/summary/traced_sources url/capabilities install_steps，留 `_verify` 块 + corrections 留痕）。⑤ **刻舟求剑践行**：星数动态非定值，verify 开头即 `info["stars_observed_at"]=_now_iso()` 打时点戳，summary/note 一律带"〔ts 取数，星数动态非定值〕"。⑥ **CLI 加 `verify` 子命令**：`python -m skillbrew verify <源目录/BV/URL> [--repo owner/repo]`，带逐 skill 进度，结尾打印核实结果+纠正清单+刹车提示（到此只核实+出清单，未安装）。⑦ **实测通过**：对 BV1UpR9BBEf5 跑 `verify`，从 r12 OCR 错草稿（mattpockock/claude-skills 404 / 81.6k 星 / 2 能力 / 5 open_questions 全未解）→ 一手核实 `mattpocock/skills`（⭐136,675〔2026-06-20T03:55:22 取数〕，默认分支 main，全仓 34 个 SKILL.md 6 类），plan.json 纠正 6 处，open_questions **5/5 全用一手数据回填标注**。⑧ **两个 bug 修复**：(a) `git/trees?recursive=1` 端点偶发 504 → `_get` 对 5xx+URLError 退避重试（`_MAX_RETRIES=3`/`_RETRY_BACKOFF=2.0`），4xx 原样返回；resolve_repo 候选取树失败留痕跳过、全失败抛"瞬时错误非未匹配"的区分报错（不静默、不硬编码 `--repo`）；(b) **诚实计数 bug**——旧 `backfill_plan` 用单子串 `key in q` 匹配（关键词不在实际问法里→漏标 3/5）且无脑写"5 条全部已解决"（谎言）；改为 `(关键词列表, 答案)` 规则匹配任一关键词、grill-me/tdd 规则仅当该 skill 真在树里才挂、`resolved_n` 真实计数报 `{resolved_n}/{total}`。**未改任何已定决策**。

- **2026-06-20 r15**：**工具化前半段（run 命令）落地✅**。把"丢链接→看视频→出草稿计划"固化成可复用 CLI，回应"把它写成可复用工具"的核心诉求（5 步计划第 1 步）。① **收编视觉批处理**：`scripts/vision_keyframes.py` 的并发看图逻辑收进 `understand.describe_keyframes`（ThreadPoolExecutor 并发 3 + 3 重试 + 5×(n+1) 退避，落 `keyframe_visions.json`），understand 模块自带视觉，不再依赖外部脚本。② **CLI 加四个子命令**：`run`（一键 采集→字幕→关键帧→视觉→消化→草稿计划，**到此为止不安装=刹车**）、`ingest`（只下载）、`understand`（只理解）、`plan`（只消化）；支持断点续跑（已存在跳过）+ `--force` 重跑 + `--skip-asr`/`--skip-vision` 降级。③ **plan.digest 容错视觉缺失**：`keyframe_visions.json` 不存在时 visions=[]，支持 D4 纯字幕降级消化。④ **路径修**：run/understand/plan 用 `cfg.data_dir/sources/<bvid>` 绝对路径（避 r14 的 CWD 坑），非模块 `_main` 的相对 `data/sources/`。⑤ **零成本冒烟测试通过**：对已有 BV1UpR9BBEf5 数据跑 `run`（不加 --force）一路跳过→打印草稿计划→刹车提示，验证编排 + 断点续跑 + 路径。**刹车设计落地**：`run` 停于草稿计划，安装需另跑 `install` 并单独授权（第 4 步）。冒烟打印出的草稿仍是 OCR 错版本（2 能力 / 错仓库名）→ 印证 verify（第 2 步）是承重墙，须把"模糊 OCR 猜测"纠正为"真正可安装"。**未改任何已定决策**。

- **2026-06-20 r14**：**授权 A 落地 + 刻舟求剑纠错**。① **刻舟求剑实锤并纠正**：r13 及各文档把去重基准记成"工作区31+用户级0"——实扫**工作区25个distinct、用户级1个(`using-coze-cli`，与工作区重复→distinct0)**，此前数字是落笔即过时的误记。授权A实际=**25→40**（非预览的46）、B=27（非33）。方法论固化：**星数/计数皆线索非事实**，写死=刻舟求剑；L1 stars 加取数时点 `stars_observed_at`。② **install A 执行**：16个核心 skill 落地（15净新增目录 + tdd整并），33个源文件全部落盘核验通过。③ **tdd 内容级整并**：Matt 的 tdd 方法论（垂直切片/tracer bullet/好测试即spec/反水平切片）graft 进本机 `Python测试技能/SKILL.md`（该 skill 已有红绿重构，不重复），四伴随文件(tdd-methodology/tests/mocking/refactoring.md)同目录放置。④ **能力台账落地**：新增 `skillbrew/registry.py`（SQLite，schema=skills+install_sessions）+ `scripts/register_install_a.py`；`data/registry.db` 登记 active=40 + merged=1(tdd)。⑤ 产出 `POST_INSTALL.md`（安装后台账报告：落地路径/台账/去重/可回滚）。⑥ `VIDEO_SCRIPT.md` 按3秒定律重写+引人注目标题。纠正 REPORT/SKILL_PACK/章程/记忆四处错数。**未改任何已定决策**。
- **2026-06-20 r13**：**顺藤摸瓜到一手仓库并核实✅**，纠掉 r12 的 OCR 待核实项；新增 D17/D18 两条决策；产三层分发文件。① **溯源核实**：视频画面 OCR 的仓库名 `mattpockock/claude-skills` 是错的→真名 **`mattpocock/skills`**（owner=Matt Pocock，TypeScript 教育者；⭐136,541；标题 "Skills For Real Engineers"；官方装法 `npx skills@latest add mattpocock/skills`）。视频星数"6万/81.6k"不准（疑把 newsletter ~6万订阅误当星数）；"约16个 skill"指核心推荐集，**全仓实有 34 个**（engineering 14 / productivity 5 / in-progress 5 / misc 4 / personal 2 / deprecated 4）。视频点名的 GrillMe/TDD 均真实存在✓。② **两个点名 skill 的真相**：`grill-me`(147字节)只是壳、内容就一句 `Run a /grilling session.`，**真身在 `grilling`**(666字节，约6句话的 relentless interview 追问提示词，**不是视频说的"42个词"**)；`tdd`(4345字节)是**多文件 skill**——SKILL.md + mocking.md + refactoring.md + tests.md，红绿重构·垂直切片·反水平切片，**安装须整目录拷**。③ **新增决策 D17**(三层分发格式：L1机器YAML+L2人读死板 打包 `SKILL_PACK.md`；L3口语化单独 `VIDEO_SCRIPT.md`)、**D18**(去重基准=扫本机已装skill，每台机器不同；分享文件去重指令不可硬编码比对目标、skillbrew 去重须扫本地优先)。④ **去重基准扫描**：本机用户级 `~/.claude/skills/`=0、工作区 `.claude/skills/`=31个已装；比对结论=基本正交(这批偏工程方法论/本机偏工具产物)、低臃肿风险，**唯一需整并：tdd ↔ Python测试技能**(方法论+语言落地合为一体)。⑤ 产出 `SKILL_PACK.md`(L1+L2，含全34技能清单+两种装法+去重指令+授权区 A/B/C/D/E) + `VIDEO_SCRIPT.md`(L3录像念稿)；旧 `REVIEW.md` 标注"已被取代"保留作历史。**待用户在授权区选 A/B/C/D/E** → 进 MVP-5 安装+台账+报告。**未改任何已定决策**。
- **2026-06-20 r12**：B站单源 MVP 闭环推进到「审核门」✅（待用户授权）。源=`BV1UpR9BBEf5`（Matt Pocock 的 claude-skills，约 16 个 Claude Code 工程技能，教科书级对口）。① **MVP-1 获取**：`ingest.py`（B站 adapter，绕开被 HTTP 412 拦的网页层/yt-dlp，直走 api.bilibili.com 公开 API：view→非 WBI playurl→DASH 选流 avc1 优先→下载 m4s→ffmpeg 重封装 video.mp4+audio.mp3）；② **MVP-2 理解**：`understand.py`（ASR=faster-whisper small/int8/CPU/zh/vad_filter 走 hf-mirror.com；**关键帧 ffmpeg scene 检测失效→改 PIL 32×24 灰度签名 + farthest-point 采样 5 帧**；时间轴对齐）+ `scripts/vision_keyframes.py`（Agnes 视觉批处理，ThreadPoolExecutor 并发 3 + 3 重试，**5/5 全过 426s**，单帧 150–241s）；③ **MVP-3 消化**：`plan.py`（DeepSeek deepseek-chat 融合 transcript.txt + keyframe_visions.json → 结构化 plan.json：2 能力 GrillMe/TDD 均 Skill 形态 + 1 溯源 + 5 open_questions，JSON 强约束 + 容错抽取）。出 `REVIEW.md`（审核门 Markdown，授权区 A 先溯源补全 16 skill / B 按现计划装 2 个 / C 改 / D 弃）。**重要发现**：仓库名/星数来自画面 OCR 待核实（mattpockock→疑为 mattpocock；字幕 6 万 vs 画面 81.6k 星数对不上）。**未改任何已定决策**；ffmpeg scene→farthest-point 的实测教训记入 5.2。
- **2026-06-19 r11**：skillbrew 包骨架落地并自检通过✅。结构：`skillbrew/` 项目根（pyproject.toml + README.md + .env + .env.example + scripts/）下建可导入包 `skillbrew/skillbrew/`（__init__/__main__/config/llm/cli）。① `config.py` 分角色加载 TEXT_*/VISION_*，**剥离行内 `#` 注释**（修掉旧 smoke_test.py loader 的坑），真实 env 优先于 .env；② `llm.py` 可插拔客户端（D15）：`chat_text`(文本组)、`chat_vision`(视觉组，本地图自动转 base64 data URI / URL 直传)，纯 openai SDK；③ `cli.py` 用**标准库 argparse**（零新增依赖，未引入 Typer，避免装包摩擦；接口可后换 Typer）提供 `doctor`/`config` 命令，`doctor` 连通性自检（文本组实测对话 + 视觉组列模型，`--vision` 才跑~5min 真看图）。**`python -m skillbrew doctor` 实测通过**：两组配置正确解析且 key 脱敏；文本组 DeepSeek 列出 deepseek-v4-flash/v4-pro + 实测对话 1.3s 自报"我是 DeepSeek"；视觉组 Agnes 列出 5 个模型(agnes-1.5-flash 等)可达。零新增安装（openai 已装）。r10 ④的"骨架"就此交付，下一步进 r10 ④的"B站单源最小闭环"。**未改任何其它已定决策**。
- **2026-06-19 r10**：用户拍板分角色方案（"好的，都按照你的计划，我们来执行"）——文本=DeepSeek(deepseek-chat)、视觉=Agnes(agnes-1.5-flash)，r9 的"待用户拍板"就此关闭。据此：① .env/.env.example 由单组 LLM_* 拆成 **TEXT_*/VISION_* 两组独立配置**（DeepSeek 与 Agnes 各自 base_url+key+model，D15 可插拔价值落地，加载器剥离行内 `#` 注释）；② D13 由⚠️待拍板转 **✅已定**；③ 第10节问题6 转 ✅已拍板；④ 开始搭 skillbrew 包骨架（config 加载分角色配置 + 可插拔 LLM 客户端 chat_text/chat_vision + cli doctor 连通性自检 + B站单源最小闭环）。**未改任何其它已定决策**。
- **2026-06-19 r9**：用真 key 实测坐实 **DeepSeek 视觉命门（否定结论）**，r8 的"DeepSeek 视觉待核实"就此关上。脚本 `scripts/probe_deepseek_vision.py`（base64）+ `probe_deepseek_vision_url.py`（公网真实狗图 URL，排除 base64 变量）交叉验证：① OpenAI 端点 `image_url` 报 400 "unknown variant image_url, expected text"；② Anthropic 兼容端点 `/anthropic/v1/messages` + Anthropic 图片块虽返回 200，但 flash/pro 两模型都直指网关把图换成了 **`[Unsupported Image]` 占位符**，模型称看不到图、且秒回（真看图会慢）；base64 与 URL 结果一致。**结论：6/18 全量上线的是网页端「识图模式」，官方 API 视觉尚未开放**（第三方中转能跑通是中转层另走通道，非官方 API）。文本 deepseek-chat 实测可用(1–2s、自报 DeepSeek、已充值)。据此 D13 改"⚠️待拍板"、第10节问题6 重写为"建议分角色:文本=DeepSeek/视觉=Agnes"，这正是 D15 可插拔设计的价值。**未改任何已定决策**，供应商分角色安排待用户拍板。
- **2026-06-19 r8**：回应用户两问（模型供应商再权衡）。①**纠正**：DeepSeek 已于 2026-06-18 上线「识图模式」，我此前"DeepSeek 无视觉"说法过时/错误；但 beta/灰度、不支持视频/多图联合（我们逐帧送图不受影响），API 视觉模型 id（第三方称 deepseek-v4-pro）未核实（官方文档被 fetch 安全策略拦截，需用户自查或有 key 冒烟测）。②**Coze 会员模型 API 查清**：Coze 无原生模型 API，是 Bot 中心（/v3/chat 调 bot_id+PAT，Bot 内部经模型网关调豆包）；能传图（object_string，需先上传 file_id）；计费=Bot 次数（0.002 元/次，积分可抵）+ 方舟 tokens（方舟单独收、不走积分）；/v3/chat 异步。③**结论**：Coze 不适配 D15 的 OpenAI 兼容抽象层（需单独适配+他人无会员用不了→与 D16 冲突），建议消化模型仍走 Agnes/DeepSeek 这类原生兼容供应商（Agnes 已测做默认，DeepSeek 待核实 API 可作替换示例），Coze 会员留给前台门面。新增第10节开放问题6。**未改任何已定决策**，供应商选择待用户拍板。
- **2026-06-19 r7**：Agnes 冒烟测试全部通过✅(用真 key 实测 scripts/smoke_test.py)：[0] /v1/models 列出 5 个模型,确切 model id = agnes-1.5-flash / agnes-2.0-flash / agnes-image-2.0-flash / agnes-image-2.1-flash / agnes-video-v2.0；[1] 文本 agnes-2.0-flash 通(7.5s,自报"由 Sapiens AI 开发的 Agnes-2.0-Flash")；[2] 视觉 agnes-1.5-Flash **真看图**——发手搓「左红右蓝」PNG,模型正确答出"红蓝分居左右",证明非瞎蒙、D4 命门坐实。⚠️但单图 298.9s(~5min),"慢也是真的"被实测坐实——批量关键帧会过慢,新增第10节开放问题5(限帧策略待用户拍板)。key 已存 .env(gitignore 保护),.env.example 占位已备,冒烟脚本留档 scripts/。
- **2026-06-19 r6**：工具链装齐并解决"卡死"——根因非权限(云电脑可装软件,非工作流沙箱禁pip)，是 pypi.org 大依赖(onnxruntime 35MB)下载反复超时 hang 死。已配 pip 全局阿里云镜像(/etc/pip.conf)重装成功。已就绪：yt-dlp/openai/faster-whisper/onnxruntime/ctranslate2/ffmpeg/Python3.13。环境坑记入第8节。Agnes 注册流程已核实(见下"Agnes 接入速查")，纠正 r5：Vision 开关是 Cherry Studio 等第三方客户端设置、非 Agnes 平台要求，直连 API 发 image_url 即可看图。
- **2026-06-19 r5**：Agnes 视觉能力已确认✅——读官方文档+论坛片段核实：Agnes 走 OpenAI 兼容 `/v1/chat/completions`，标准 `content:[{type:text},{type:image_url}]` 格式即可图像输入(非仅生成)。视觉理解模型 = **Agnes-1.5-Flash**(多模态文本+图像,识图/OCR提取/图表分析,轻量高并发适合批量关键帧；定位"简单图片解析即问即答",复杂代码读取偏弱→Claude 兜底)；文本模型 = **Agnes-2.0-Flash**(纯文本,工具调用/Thinking/编程,负责字幕消化+执行计划)。~~⚠️平台需手动勾选 ✓Vision 开关~~【r6纠正：该"勾Vision开关"出自 Cherry Studio 等第三方客户端教程，是客户端设置、非 Agnes 平台要求；直连 API 发 image_url 即可看图，无需任何开关】。据此 D4 依赖✅、D13 细化模型分工，MVP 不再阻塞。
- **2026-06-19 r4**：核实 Agnes(免费+OpenAI 兼容✅；图像理解能力正读官方文档+论坛核实⚠️) → D13 改 Agnes 优先(字幕+视觉都用, DeepSeek 等可插拔)；D15 模型无关/可插拔；D16 改"开放给他人须有 API key 输入位"；清掉 D9/D12 重复与第10节开放问题；D14 安全脱敏确认。MVP 视觉兜底：Agnes 不能看图则由 Claude 顶上(不阻塞 MVP)。
- **2026-06-19 r3**：定 D1(不用 Coze 工作流)、D10(独立仓库复用 whale 获取层逻辑)、D11(纯 Python)；看过 whale 仓库，明确复用点=抖音反爬+ASR+ffmpeg 经验，产物方向不同需新写。
- **2026-06-19 r2**：按用户反馈重构 —— 输入多模态化、视频真看(关键帧+视觉)、溯源一手、产物综合型(先计划后选形态)、安装记录可分享/可移除、防臃肿去重、本地核心+Coze门面分析。
- **r1**：初版（仅视频→Skill 的简化管线）。
