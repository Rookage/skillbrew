# HANDOFF · skillbrew Step 5（r19）✅ + r20 Path A✅ + recommend 判断步积木 A–G 全✅（含 D）→ recommend 闭环全通

> 写给明天的我自己：从这份文档 + 记忆里的 `skillbrew-step5-handoff` 指针加载断点，继续往前推进。
> 落笔日期 2026-06-20（深夜补 r20；r21/r22/积木A–G/D 后续补）。**最新节 = 顶部「✅ D22 调用方式渲染完成（record.py）」**（用户诉求：先把 skillbrew 代码写完别拖；record 看板新增「怎么调用装好的技能」段，补齐 recommend.py:17-18 委派的 D22，8 零token 测试 + 零回归 diff + 幂等 全绿）。其下「✅ 技能可见性修复（本机两抽屉）」（已修+终检绿）、「积木 D 完成」「积木 A–G 纯本地部分完成」「r22/r21 更新」「r20 完成总结」为历史。**recommend 判断步 7 块积木全部完成、自测绿**；ingest→understand→plan→verify→dedup→recommend→install→record 闭环全通。下文 §1-§9 为 r19 落地规格留档（历史记录，勿再照抄执行）。

## ✅ D22 调用方式渲染完成（record.py，2026-06-20，用户诉求「先把代码写完别拖」）

**用户诉求**：技能的问题先搁置，直接写 skillbrew 代码别再拖。本次落地 = **D22「怎么调用装好的技能」渲染**（recommend.py:17-18 早把这段委派给 record 看板，此前一直是空的）。这是 R1「装了不自动调用」痛点的 **MVP 桥接**：报告说清每个装上来的能力「是什么 / 怎么调用」，人照着调（完整自动调度器 R1 仍留 v2+，未动）。

**实现（`skillbrew/record.py`，纯数据驱动零硬编码）**：
- `_trigger(desc)`：从 description 抠触发提示词——含 `Use when…` 从那里起取（即该技能的唤起条件），否则取首句兜底；压一行、`|` 转义、超 110 字符截断带 `…`。
- `_invoke_hint(name, form)`：按形态给**通用调用机制**（不写死具体技能，D22 反盲盒）——Skill「任务相关时自动加载；或点名『使用 X 技能』」、MCP「配进 Claude Code 后自动暴露工具」、代码/配置各有入口；form 缺省当 Skill。
- `_d22_invoke_section(g, heading)`：本次落盘的能力逐个列表——表头 `| # | @名 | 形态 | 触发提示词 | 怎么调用 |`，数据取 `g["new_installed"]` × `g["by_name"]`(display_name/description) × `g["reg_active_by_name"]`(form)。**优雅降级**（同 G3 口径）：`really_installed=False`(dry-run 未 `--approve`)→ 不铺表、提示「未落盘暂无可调用项 + 先跑 recommend 挑子集」；真装但本批无 new→「无可调用项」不铺空表。带 recommend→末注 approved 子集（D20 挑着买）。
- 接线：`_gen_record()` 的 §8（开源合规后）、`_gen_dashboard()` 的 §7（诚实提示后）各 `L.extend(_d22_invoke_section(...))`。**独立于 `rec`**——基准源无 recommend.json(rec=None) 该段照样出。

**验证（全绿）**：
1. `tests/test_record_d22.py` **8/8 ✓**（零 token，不调 LLM 不要 key，同 test_judge_ai_mock 风格）：_trigger 抠 Use when/首句兜底/截断、_invoke_hint 按形态、真装表格逐个列、dry-run 降级、空批无可调用项、带 recommend 注 approved。
2. **零回归**：`python -m skillbrew record BV1UpR9BBEf5`（无 flag，dedup.json baseline.skill_dirs 含两抽屉→复现基准）vs D22 前基线，`diff` = **纯插入**（RECORD `134a135,156` / DASHBOARD `109a110,131`），旧段零修改零删除。13 技能表正确渲染（4–13 含 Use when；1–3 首句兜底；`setup-matt-pocock-skills` 截断）。
3. **两分支都对**：BV1UpR9BBEf5 真装(2 sessions→13 行表)；BV1Kj9zBWEjS dry-run(0 sessions→降级措辞，非 832 行表)。
4. `test_judge_ai_mock.py` **7/7 仍 ✓**（无回归）；**幂等**：连跑两次 `diff -q` 字节级一致。

**代码口径**：与现有 record.py 同口径、数据驱动（一手数据 install_list/registry/dedup），形态泛化（Skill/MCP/代码/配置），不写死本机。GitHub 代码零特殊化。新增测试文件 `tests/test_record_d22.py`。

---

## ✅ 技能可见性修复（本机两抽屉，2026-06-20，用户明确诉求）

**用户诉求**：下载下来的 skill 要在「已安装技能」里看得见、能调用；当前看不到。**两件事分开**（用户原话）：① 放 GitHub 给普适 Claude Code 用的代码保持通用、不为本机特殊化；② 本机环境特殊（扣子3.0 + 云电脑 + 云部署 Claude Code + 扣子调试过），skill 要加载到对的地方，该调整就调整。

**根因（一个，同时解释 finding-3 + R1）**：本机有**两个技能抽屉**——
- **项目级（可见）** = `…/workspace/.claude/skills/`（coze-3.0-expert、engineering-*、中文名等 ~40 个都在这、能调用）。
- **用户级（不可见）** = `/root/.claude/skills/`（matt-pocock 14 个下在这，本环境不加载）。
skillbrew **默认安装/扫描目标 = 用户级**（`cli.py:666 --target-dir 默认 ~/.claude/skills`、`cli.py:354 默认扫 ~/.claude/skills`），但**本扣子环境只加载项目级** → 下载的 skill 进了不被看的抽屉。finding-3「磁盘14 vs 台账53」同因：record 默认扫用户级(14)，台账却是从项目级扫的(53)。

**已修（只动本机文件 + 本机台账，GitHub 代码零改动）**：
1. 搬 13 个 matt-pocock 技能：用户级 → 项目级（`using-coze-cli` 项目级已有正本、跳过碰撞）。
2. registry 台账 13 行 `install_path` 改指项目级（`source=mattpocock/skills`，updated_rows=13）。
3. 散落 `using-coze-cli` 用户级副本与项目级正本**有实质差异**（用户级多 `coze-claw` 模块+若干参考文档，项目级多 `coze-agent`）→ **不删，保留**，留作可选后续合并。
4. 终检：registry active=53、53 条 `install_path` 全部磁盘存在、零缺失；项目级抽屉=53 目录 == 台账53。**finding-3 由此消解**（扫项目级即 53==53）。

**本机今后用法**：在本环境装/记 skill，给 skillbrew 指项目级抽屉——`install --target-dir …/workspace/.claude/skills/`、`record/dedup --skills-dir …/workspace/.claude/skills/`（skillbrew 已支持这两个 flag，非代码改动）。**GitHub 通用代码默认仍是 `~/.claude/skills`**（对普通 Claude Code 用户那才是可见抽屉，正确，勿改）。

**扣子文档**：docs.coze.cn 被本机网络策略封锁（WebFetch 报不安全、WebSearch 空）；改用本地 `coze-3.0-expert/references/platform-overview.md` 确认「本地 Agent 接入：可接入本地运行的 Claude Code …Coze 3.0 可直接调度它」——即 Claude Code 跑在 agent workspace 内、项目级抽屉即本 agent 可见抽屉，与磁盘实情一致。

**注意**：技能要出现在「已安装技能」列表需 Claude Code 重新扫描（新会话/重载）；本会话内无法强制触发，文件已就位即生效。

---

## ✅ 积木 D 完成（ai 模式 LLM 判断，2026-06-20，用户在场授权烧 token）

**recommend 判断步最后一块积木 D 已实现并验证通过 → 7 块积木 A–G 全部完成、recommend 三模式（keyword/manual/ai）全可切、闭环全通。** 用户明确授权「现在就上，我在场可以烧 DeepSeek token，但你自己要随时监控，发现状况不对随时停」。

**实现（`recommend.py` 积木 D 节 + `cli.py` ai 分支）**：
- `judge_ai(candidates, profile, *, descriptions, cfg, chat_fn, batch_size=10, limit, on_batch, timeout)`：分批喂文本模型（默认 10 条/批），每批一次 `chat_text` → 解析 JSON 数组 → 按 name 映射成 `Judgment`。喂「本机画像 + 候选名/分类/描述」，让模型知「已有什么」避免推重复（与 keyword 同思路）。
- **D21 热插拔**：`cfg.text` 文本模型，任意品牌皆可（不写死 DeepSeek）；`chat_fn` 可注入（默认 `llm.chat_text`，测试注入 mock 即零 token、不要 key）。
- **容错（防静默漏判，与 `merge_judgments` 同口径）**：单批调用/解析失败 → 整批降级「不值得装」+ reason 含失败原因；模型未给出某候选 → 降级「不值得装·模型未给出该候选判断」；绝不拖垮整次。
- **`_extract_json_array`**：去 ```json 围栏 + 直取数组；数组包进对象（`{"results":[...]}`）则抠 list 值；方括号不平衡走平衡括号兜底（对齐 `plan._extract_json`）。
- **`--limit N`**：成本控制，只判前 N 条 new（未判的由 `merge_judgments` 兜底不值得装）。
- **`on_batch` 回调**：CLI 打印每批进度（`批 i/n（bs 条）→ ok/FAIL→整批降级`），D22 透明 + 用户在场可监控。
- **CLI ai 分支**：D21 前置守卫 `if not cfg.text.is_complete: 报错+提示用 keyword/manual + return 1`（不烧 token、不走死路）→ 派发 `rec.judge_ai(..., chat_fn=llm.chat_text, limit=args.limit, on_batch=...)` → 同 `merge_judgments` + `assemble_report` 装配（与 keyword/manual 完全同路径，零分叉）。

**验证（三层，由俭到丰）**：
1. **零 token mock 自测**（`tests/test_judge_ai_mock.py`，7/7 ✓，不调 DeepSeek、不要 key）：正常 JSON 数组解析+映射 / 分批(2/批)拆 3 批+name 匹配+未给出降级 / 调用异常整批降级 / 畸形回复降级 / 数组包对象抠出 / `merge_judgments` 衔接(skip→已装·merge→建议整并·approved 正确) / `--limit` 成本控制。
2. **真模型往返**（`recommend BV1Kj9zBWEjS --mode ai --limit 3`，1 次 DeepSeek 调用，~1k token）：批 1/1 → ok；3 条 new（2d-games/3d-games/3d-web-experience）全判「值得装」，reason **具体可追溯**（「本机无 2D/3D 游戏开发能力，描述充分实用完整」—— 确实读了画像+描述并据此推理，非橡皮图章，D22 透明达标）；829 条 limit 外 new 正确降级不值得装；33 merge/5 skip 兜底正确；`source_verdict=挑着装`、`approved=3`、报告落盘。测后已恢复 keyword 版（461 approved，真实建议；limit=3 的 approved=3 是测试假象，避免误导后续 install）。
3. **回归**（零 token）：重跑 `--mode keyword` → approved=461、by_verdict{值得装461/不值得装371/建议整并33/已装5} 与改动前一字不差 → cli.py 加 elif ai 分支未碰坏 keyword/manual。

**安全/成本**：ai 模式默认不跑（keyword 是 default）；须 `--mode ai` 显式 + D21 守卫 + 用户在场；`--limit` 控成本；单批失败降级不拖垮。keyword/manual 恒可用（无 key 不走死路，D21 安全网）。

**下一步候选**（待用户定夺，非阻塞）：① 全量 ai 判断（832 new × 10/批 ≈ 84 次调用，烧较多 token，须用户点头）；② finding-3（落盘漂移 磁盘14 vs 台账53）独立运维项；③ R1 调度器（v2+）；④ GitHub 上传（推前重生成 DeepSeek/Agnes key、私有仓库、脱敏）。

---

## ✅ recommend 判断步（积木 A–G，纯本地部分）完成（2026-06-20）

**乐高拆法 7 块，前 6 + G1/G2/G3 全做完、自测绿；只剩 D（ai 模式，烧 token，待用户在场）。** 全程纯本地、不调 LLM、不烧 token、不要 key（D21 安全网）。

- 积木 A（核心：数据模型 + 汇总 + 报告装配）/ E（`build_profile` 本机画像，复用 dedup 基准）/ B（`score_keyword` 规则打分）/ C（`pick_manual` 人工勾选）/ F（`recommend_health` 三模式自检）—— 均在 `recommend.py`，纯标准库。
- 积木 G1：CLI `cmd_recommend`（读 dedup.json+install_list.json → `build_profile` → 按 `--mode {keyword,manual,ai}` 派发；ai 友好提示「未接」+return 1）+ `--source-skip`（整源跳过置空 approved）。三模式自测绿。
- 积木 G2：看板接入判断步——`record._gather` 读 `recommend.json`（跑了才有、没跑 None→优雅降级）；`_gen_dashboard` §2 加 verdict 分布饼（值得装/不值得装/建议整并/已装）+ source_verdict + approved 子集 + 逐 verdict 说明（D19/D22 反盲盒）；§6 诚实提示 recommend-aware。
- 积木 G3：**finding-2 修复**——`really_installed = bool(src_sessions)` 旗标。True（基准源 sessions≥1）→ 原措辞一字不改（零回归）；False（dry-run sessions=0）→ RECORD §0/§1标题/§1诚实/§3/§6 + DASHBOARD §2饼/§2点/§6 降级「待装候选」「无需回滚」。两个生成器同口径。

**自测（record 重跑两源，record 只读刹车成立）**：
- dry-run 源 BV1Kj9zBWEjS（sessions=0，有 recommend.json·keyword·source_verdict=挑着装·approved=461·by_verdict{值得装461/不值得装371/建议整并33/已装5}）：DASHBOARD §2 verdict 饼 + 源级=挑着装 + approved=461 全出现；finding-2 旧措辞（「本次新装 832」「--approve 装的」）已消失，降级为「待装候选 832」「无需回滚」。✓
- 基准源 BV1UpR9BBEf5（sessions=2，**无** recommend.json→rec=None 降级）：`diff` 新 RECORD.md/DASHBOARD.md vs `/tmp/RECORD_baseline_old.md`/`/tmp/DASHBOARD_baseline_old.md` → **零变化**（really_installed=True + rec=None → 全走原分支）。✓

**积木 D（ai 模式 LLM 判断）已于本节上方「✅ 积木 D 完成」落地并三层验证通过 —— 7 块积木 A–G 全部完成、recommend 三模式全可切、闭环全通。** 下一步候选（待用户定夺，非阻塞）：全量 ai 判断 / finding-3（落盘漂移 磁盘14 vs 台账53，pre-existing 独立运维）/ R1 调度器（v2+）/ GitHub 上传（推前重生成 key、私有仓库、脱敏）。

---

## ✅ r22 更新（2026-06-20 用户拍板·本节优先于下方 r21）

**用户这轮提了 2 条新决策 + 1 条延后需求，均已落档 PROJECT_CHARTER §4（D21/D22 决策表）+ §9.1（R1 延后需求）+ §11 r22 修订记录。未改任何已定决策，仅新增。**

- **D21 模型前置·文本必备·视觉可选优雅降级**：用户发现逻辑 bug——要跑本工具须两种 LLM 能力（文本+图片识别），若他人无 DeepSeek/Agnes 是否整个动不了？定性：**前置条件=至少 1 个大模型**（无 LLM 则消化步骤跑不动、工具完全不可用）；**任一品牌文本模型皆可**（所有 LLM 都有文字能力，不写死 DeepSeek，契合 D15/D16 通用化）；**视觉为可选**——无视觉能力时**不卡死**，降级「视频转语音→语音转文字」路径（识别质量较低、不能抽关键帧看画面），主动建议换多模态模型但**不阻断**；配置=text_model(必填)+vision_model(可选)。区别于 D13（D13=本机具体选型 DeepSeek+Agnes；D21=通用前置与降级规约）。
- **D22 反盲盒·透明可追**：直击「AI 全黑盒决定、人说好了但看不到、没安全感」的恐惧——① 消化素材后**必须**与人类交互确认才安装（强化 D19/D20 交互门，绝不黑盒自动装）；② 安装时说明每个功能**是什么**；③ 可视化报告须含「装了什么 / 新增哪些能力 / **以后怎么调用**」——尤其「调用方式」（@skill 名 / 触发提示词），让装了的能力能被找回、能被调用。
- **R1 延后需求（v2+，新增 §9.1）**：用户痛点——skill 装了一堆但 Agent 不会自动调用，须 `@skill` 或读其 prompt 才触发，否则装 1000 个也不调。定性为与「安装」正交的另一层「调度器」（执行前扫已装能力→判该加载哪些→加载→执行），非 skillbrew 安装器职责；MVP 仅靠 D22 报告带「调用方式」让人工/Agent 手动调，完整自动调度留 v2+ 独立组件。

**下一步（同 r21，待用户确认架构后实现；⚠️ 涉 LLM 的判断勿在用户不在时盲跑烧 token）**：我已提案 **recommend 判断步 5 点架构**——① recommend 三模式可切（`ai`=用户自带 key 热插拔默认 DeepSeek / `keyword`=无 key 不烧 token / `manual`=列清单人工选，无 key 用户不得走死路）；② 安装建议清单 + 交互菜单（D20 挑着买）；③ 复用 dedup 扫描出「本机已有哪些能力」画像喂判断（D18 动态基准，不硬编码）；④ 看板加新状态（judged 不值得装 ≠ installed/skipped-dup）+ finding-2 折入（sessions=0 措辞降级，避免重复劳动）；⑤ doctor 自检（文本必备/视觉可选/降级路径提示）。**用户尚未回「顺我就开写」**，先停在落档。

---

## ✅ r21 更新（2026-06-20 用户拍板·本节优先于下方 r20「下一步」）

**用户认可 r20 对 davila7 源的判断（不盲目整装 832），并拍板两条新决策（已写进 PROJECT_CHARTER §4 决策表 + §11 r21 修订记录）**：

- **D19 判断先行·协助人类判断**：用户盲目丢素材 → skillbrew 先消化+判断 → 给「值得装/不值得装/挑着装/整源跳过」**主动建议** → 人定。固化「代替用户人肉看视频判断有用才执行」的行为为制式规范。**dedup 只判「是否重复」≠「是否值得装」须分开**（DASHBOARD §6「代码去重只判是否重复、不判是否值得装」诚实注升级为主动建议）。
- **D20 安装粒度·挑着买**：大集合/配置商店源**禁整目录盲拷**；install 须支持「单组件选装 / 购物车组合 / npx 一键装」；install_method 由源形态决定（非写死 copy_whole_dir）。
- **对 BV1Kj9zBWEjS 的数据驱动建议（已交付用户）**：**整源跳过安装**——870 中 ~320 个学术/科研数据库（scientific 139 + ai-research 框架 ~130）+ ~50+ SaaS 工作流（notion/slack/jira/linear/railway/pocketbase/sentry/neon/supabase/vercel/stripe/shopify/figma/telegram/discord）非用户方向，余者多与已有 skill 重叠（code-review*/security-*↔review/security-review、deep-research↔deep-research、docx↔docx、database-*↔数据库模式设计、obsidian-*↔obsidian-vault、writing-skills↔writing-beats/fragments/shape、development↔engineering-*）；唯一值得**当参考（非安装）**的是 skill-authoring 元技能簇（skill-creator/developer/judge + cc-skill-coding-standards/continuous-learning/strategic-compact/security-review + template-skill）——用户正造 skill 管理器，这些是「别人怎么造/评 skill」的一手经验。**该源真实价值 = 架构案例（逼出 D19/D20），非技能来源。**
- **Coze 会员 API 模型调用：舍弃**（用户定——太复杂、无法成为公开代码的一部分；关闭 D15 项下 dormant 的 Coze 3.0 API 问题）。

**下一步（待用户确认设计分叉后实现；⚠️ 涉及 LLM 的判断勿在用户不在时盲跑烧 token）**：
1. `recommend` 判断步：用 **LLM（DeepSeek）还是启发式**？（「值不值得装」本质主观、用户相关 → 倾向 LLM + 用户画像输入，但烧 token，须用户点头）
2. 「用户方向/已有能力」如何作为输入 → **用户画像**（扫本地 `~/.claude/skills` + 台账，生成方向摘要喂给判断）
3. 选装 UI/cart 语义：CLI 交互式多选？还是 plan 阶段就标「挑着装候选」？
4. record/DASHBOARD 反映「judged 不值得装」状态（区别于 installed / skipped-dup）。

**finding 2 小修**（纯本地、低风险、不烧 token，可顺手做）：record.py sessions=0 时 §2/§6 措辞降级为「去重新装候选 N」（832 是计划非安装）。
**finding 3**：落盘漂移（磁盘 14 vs 台账 53）pre-existing，独立运维项，不阻塞。

---

## ⚠️ LoopGuard · 死循环解除 / 自我校准机制（续接第一眼必读）

> 起因：凌晨我陷过死循环（`TaskUpdate` 连调十几次、每次报缺 `taskId`、却重复同一坏调用不修正）。用户要求自带刹车。详见记忆 `loopguard-self-calibration`。

**触发信号（任一即警觉）**：同一工具连续失败 ≥2 次且报错相同 / 工具报"缺参数"但我以为已传 / 连续空输出轮次 / 对同一报错原样重试不改参数。

**触发后 STOP-INSPECT-ROUTE**：
1. STOP：停止重试该工具，禁止相同参数再调。
2. INSPECT：工具级故障→绕开（换工具/换路径）；任务级卡点→换路径或跳过、落盘卡点、往下做能做的。
3. ROUTE：降级执行，优先"有产出地往前走"，绝不原地空转。

**恢复锚点**：触发后第一件事 Read 本 HANDOFF 重建断点；连 Read 都坏则只输出该轮文字计划等用户回。

**本会话硬护栏（实测）**：`TaskUpdate` 稳定吞参数 → **禁用**，任务对账全走 §7 文字记录，不碰该工具。

---

## ✅ 完成总结（2026-06-20 末，Step 5 收尾）

Step 5（r19）**全部落地并验证通过**：

1. **record.py 数据驱动改造完成**——`_gather()` 加读 `plan.json`（取 `ocr_note`/`verify_how`/`verify_corrections`）；RECORD §5 + DASHBOARD §0/§1/§4 的硬编码 `25/40/54`/`mattpockock/claude-skills`/`81.6k`/`BV1UpR9BBEf5` 全部替换为现取数据；OCR 误记值走**方案A**（正文引 `g["ocr_note"]` 全文、Mermaid 节点用 `g["verify_corrections"][0]` 文本，不写死具体错值）；`_cumulative_flow`/`_session_label`/`_session_arrows` 三个辅助函数已接线调用；`skill_dirs` 口径 bug 已修（默认读 dedup.json baseline.skill_dirs）。
2. **CLI `record` 子命令已接**（`cli.py`：`cmd_record` + `p_rec`）——`--skills-dir` 为**追加**语义（预合并 dedup 默认目录 + 追加，因 `record.record()` 传 list 是替换非追加）；`_resolve_source` 处理 BV→源目录。
3. **验证全过**：`python -m skillbrew record BV1UpR9BBEf5` → sessions=2 / this_run=13 / 磁盘 53 == 台账 53 ✅一致 / orphans=[] missing=[]；grep record.py 源码 `81.6k|mattpockock|25 distinct|40 active|54 distinct|BV1UpR9BBEf5` **0 命中**（零硬编码字面量）。
4. **幂等回归通过**：备份当前 RECORD.md/DASHBOARD.md → 重跑 `record` → 两份产物**字节级一致**（无时间戳漂移，纯数据驱动稳定）。
5. **诚实注保留**：RECORD §2 口径差异注（会话1 active/会话2 distinct）+ DASHBOARD §6「代码不判是否值得装」——改造时保留。
6. **PROJECT_CHARTER.md r19 修订记录已补**（newest-first，r18 上方）。
7. **刹车设计成立**：record 只读——不调 LLM、不下载、不改台账，`on_progress` 仅 read/write 两阶段。

**下一步 = r20 回归测试**（章程 5 步计划收尾）：端到端重跑 BV1UpR9BBEf5 的 run→verify→dedup→install→record，确认结果与手工跑一致。⚠️ **三大风险，勿在用户休息时盲跑**：
1. **dedup 重跑会覆盖历史 provenance**——当前 `dedup.json` 记的是**代码 install 前**基准（distinct=41/new=15/skip=16）；现在台账已 active=53，重跑 dedup 会把 13 个已装 skill 判成 `skip`、baseline 改写，**覆盖掉 RECORD/DASHBOARD 引用的历史 dedup.json**。所以 r20 不能在原源上裸重跑 dedup。
2. **install `--approve` 改台账/磁盘**——会动 `registry.db` 与 `~/.claude/skills`，破坏当前已验证的 53==53 状态。
3. **run/verify 耗 API + 网络**——run 用 DeepSeek+Agnes+B站 OCR，verify 用 GitHub raw；云电脑网络可能 hang（见记忆 `cloud-computer-pip-mirror`）。

**r20 推荐做法**（任一，需用户在场决策）：(a) 用**全新 BV 源**做干净闭环回归（不碰现有 BV1UpR9BBEf5 台账）；或 (b) 在原源上重跑前**先整目录备份** `data/sources/BV1UpR9BBEf5/` + `registry.db` + `~/.claude/skills`，跑完比对、可回滚。本会话已在原源上完成 `record` 的幂等回归（字节级一致 + 53==53），Step 5 组件本身已验证，无需急着跑全链路。

**🔍 r20 前置发现 → 已修复✅（2026-06-20 夜扫出，同夜改代码 + 语法自检通过，未跑 verify 实测，等用户在场一起测）**：

扫 skillbrew 代码（`.py`，排除数据文件）刻舟求剑违规，发现 `verify.py` 的 `backfill_plan()` 把本源（BV1UpR9BBEf5）的 OCR 纠错叙事**硬编码进模块**——换新源跑 r20-path(a) 会写**假留痕**：
- `verify.py:331-337` `new_sum`：**无条件**写「草稿曾因画面 OCR 误记仓库名 mattpockock/claude-skills 与星数 81.6k」进 `plan["summary"]`——新源没犯这错也会被写上。
- `verify.py:348-351` `ts0["note"]`：**无条件**写「草稿 OCR 误记为 mattpockock/claude-skills（404）…（树含 grill-me/tdd）」进 `traced_sources[0].note`——新源同样被假标。
- `verify.py:379-391` 关键词规则答案含 `81.6k`/`6万 newsletter`/`16个·14个`/`grill-me`/`tdd` 等本源 specifics；这些是**条件触发**（open_questions 关键词不命中即静默），新源上不主动造假，但仍是源特化逻辑塞在通用模块里。

根因：`backfill_plan` 整体按 BV1UpR9BBEf5 手调、非通用。这是 record.py 方案A 的**上游**——record 读的 `ocr_note`/`verify_corrections` 就是 verify 写的；verify 不通用 → record 再数据驱动也救不了新源假留痕。

修法（待用户在场，因需重跑 verify 验证，烧 API + 会覆盖现 plan.json，先备份）：第 342 行已捕获 `old_url = ts0.get("url","")`（draft 原值，覆盖前）；同理捕获 draft 原 `name`。① **条件化**：仅当 draft 原 repo/url ≠ 一手 `full_name`/`html_url` 时才写「OCR 误记」叙事；用**实际 old→new 值**插值，不写死 `mattpockock/claude-skills`/`81.6k`/`（404）`。② summary（331-337）同理条件化。③ 关键词规则答案（379-391）去 specifics：星数答案改成 `⭐{stars}（{ts} 取数）…画面/字幕所示为草稿 OCR，以一手为准`，不写 `81.6k`/`6万`。

**结论**：r20 真正干净闭环 = 先把 `verify.py` `backfill_plan` 通用化（本发现）→ **✅ 已完成（2026-06-20 夜：代码改 + `py_compile`/`import` 语法自检通过）**，再用**新 BV 源**跑 run→verify→dedup→install→record——那才是有意义的回归。**未跑 verify 实测**（需 DeepSeek/Agnes API + 会覆盖现 plan.json，等用户在场一起测）。对 BV1UpR9BBEf5 向后兼容：repo_mismatch=True → 仍写 OCR 叙事、corrections[0] 同原文，重跑 DASHBOARD 边标签不变。本次未盲改无测试（代码改动 + 语法自检 = 安全；跑 verify 才烧 API，留用户在场）。另：`scripts/register_install_a.py:44` 的 `VIDEO="BV1UpR9BBEf5"` 是一次性登记脚本，非工具链，不动。

---

## ✅ r20 完成总结（2026-06-20 深夜，新源干净闭环回归 Path A）

用户给新 B站源 BV1Kj9zBWEjS（Claude Code Templates by Daniel Avila/@davila7），原话："再一次主动执行任务，主动消化。跑一个可复用的项目代码。" **Path A = 用全新源跑干净闭环，不碰现有 BV1UpR9BBEf5 台账**（规避 r19 末标的"原源裸重跑 dedup 覆盖历史"风险）。

**全链路在新源跑通（零 mutation，用户在睡）**：
- `ingest→understand→plan`（DeepSeek 草稿 + Agnes 看关键帧 5 张）。OCR 把一手仓库 `davila7/claude-code-templates` 误记为"Davila GitHub主页"——正好触发 backfill 通用化测试。
- `verify`（task balsaluv3，exit 0，~460s，纯 GitHub raw 不烧 LLM）：verified_repo=`davila7/claude-code-templates`、stars=**28184**、stars_observed_at=2026-06-20T13:05:52、how_resolved="草稿 repo davila7/claude-code-templates 直查命中"、skill_total=**870**、corrections=**9**（含关键条 `traced_sources[0].name: Daniel Avila GitHub主页 → davila7/claude-code-templates`）。870/870 skill 全 enrich、fetch_error=0。
- `dedup`（exit 0）：new=**832** / merge=33 / skip=5 / deprecated=0（对基准 distinct=54）。
- `install --dry-run`（**未 --approve**，exit 0）：算出"将装 new 832 个"，零落盘零写台账 ✅（不污染 53==53 基准 + ~/.claude/skills）。
- `record`（exit 0，只读）：生成本源 RECORD.md + DASHBOARD.md。

**r20 核心目标——backfill_plan 通用化——确认通过**：
- 通用化条件 `repo_mismatch = bool(old_name) and _norm(old_name) != _norm(full)`：本源 old_name="Daniel Avila GitHub主页"、full="davila7/claude-code-templates" → 不等 → 正确触发 OCR 误记叙事，用**实际 old→new 值**插值（不写死 `mattpockock/claude-skills`/`81.6k`）。
- grep 新源目录 `mattpockock|claude-skills|81.6` → **0 命中**（零硬编码旧源泄露）。
- `corrections[0]` 仍是 summary、首个 append——record.py 边标签位置读不变，向后兼容✅。
- regex 修复（verify.py:91，限定 owner/repo 字符集 `[A-Za-z0-9-]`/`[A-Za-z0-9._-]` + lookahead `(?=[^A-Za-z0-9._-]|$)` 锚尾，防中文 prose 混入 repo 名致 urlopen ascii 炸）——端到端再验稳定。
- 上文 r19 末段的"**未跑 verify 实测**" → 本段已**实测补齐**：verify 跑通、9 条 corrections 全是真实 davila7 值。

**三个发现（落档，不阻塞 r20，待用户在场定夺）**：

1. **架构错配（最重要）**：`davila7/claude-code-templates` 是**配置商店**（870 组件、6 类：agents/commands/settings/hooks/mcps + 购物车 `npx claude-code-templates@latest` 一键装），不是"skill 集合"。skillbrew 当前闭环按 skill-collection 形状走，对它产出"整目录装 832 个"——荒谬（没人会一键装 832 个配置）。正是用户 scope 钉正的：[[project-artifact-not-just-skill]]——"别退化为 skill 加载器，有时产物是直接用于生产力的操作步骤"。→ **下一步架构议题**：能力/产物抽象要支持「按需选装单个组件 / 购物车组合 / npx 一键装」等形态，而非整目录拷。870-scale 也暴露 `enrich_with_frontmatter` 串行 raw fetch 线性耗时（~460s，非 bug，但大仓会慢）。
2. **record.py 模板假设 ≥1 安装会话**：本源 sessions=0（dry-run 未真装），但 DASHBOARD §2/§6 仍写"本次 --approve 装的 832 个"——0 会话时无"本次新装"，832 是**计划**非**安装**。§0 正确显示 sessions=0，§2/§6 措辞自相矛盾。→ 小修：sessions=0 时降级为"去重新装候选 N"措辞。
3. **落盘漂移（pre-existing，非本次造成）**：record 检出"磁盘 active distinct 14 == 台账 53 → ⚠️不一致"，39 个"台账有/磁盘无"（含 coze-* 系列、engineering-*、productivity-*、中文名 skills）。record 只读、本次 install 是 dry-run——非 r20 引入。疑似 `~/.claude/skills` 曾被清理（云电脑凌晨崩溃恢复？见 [[cloud-computer-pip-mirror]]）。→ 独立运维项，不阻塞。

**r20 结论**：可复用工具链（skillbrew CLI）在新源上端到端回归通过，backfill 通用化 + regex 修复实战验证。**章程 5 步计划收尾完成**（r15→r20 全通）。下一步 = 发现 1 的架构演进（能力/产物抽象支持配置商店），需用户在场定方向。

**未做（按约定）**：GitHub 上传（用户在场再说，推前重生成 key、私有仓库、脱敏，见 [[git-staged-checkpoint]]）；未 `--approve`（保 53==53 基准 + 磁盘干净）。

---

## 0. 一句话现状（历史留档：本次落地前的起点）

Step 5（r19）要把「安装记录 + 看板」从**手写 Markdown**变成**代码生成**，要求完全从一手数据（`registry.db` / `dedup.json` / `install_list.json` / `plan.json`）驱动，**不许手写死任何数字**（刻舟求剑 §5.3）。

今天已完成：`record.py` 加了 3 个数据驱动辅助函数 + 修了 `skill_dirs` 口径 bug。
今天卡住：辅助函数写好了但**没接到生成器里**，RECORD/DASHBOARD 里仍有一批硬编码；`_gather` 还没读 `plan.json`；CLI 没接 `record` 子命令；没跑生成、没验证、没补 PROJECT_CHARTER r19。

---

## 1. 项目背景（速览）

- **skillbrew**：开源项目「AI 能力包管理器」，像 homebrew 但装的是 AI 能力（Skill / MCP / Code / Config）。
  核心流程：素材（B站视频/网页/文件）→ 自动消化 → AI 可读执行计划 → 经授权后执行 → 安装为 AI 能力 → 生成安装记录与累计看板。
- 锚文件：`ai-self-evolution/PROJECT_CHARTER.md`（唯一核心章程，修订记录 newest-first）。
- **5 步可复用工具计划**（章程 D18）：r15 run/ingest/understand/plan ✅ → r16 verify 溯源 ✅ → r17 dedup 去重 ✅ → r18 install + registry 安装与台账 ✅ → **r19 record + 看板（当前）** → r20 回归测试。
- **刹车设计 D18**：`run` 停 plan；`verify` 停 install_list；`dedup` 停报告；`install` 默认 dry-run，`--approve` 才真装；`record` 只读（不改台账、不下载、不调 LLM）。
- **刻舟求剑 §5.3**：星数、安装数等计数会变化，**不能写死**；必须带 `stars_observed_at` 取数时点；所有 before/after 数字从 `install_sessions` 现取。
- **LLM 分工**：TEXT=DeepSeek，VISION=Agnes；verify/dedup/install/record **不用 LLM**（纯标准库 + GitHub raw，不耗配额、不要 key）。
- **skill_dirs 口径铁律**：去重与记录必须扫同一批目录（`~/.claude/skills` + 工作区 `.claude/skills`），否则出现虚假「孤儿/缺失」。
- **台账 = SQLite 文件** `data/registry.db`：每行一个 skill，「你落盘就是什么」（落盘核对：磁盘 active distinct 必 == 台账 active）。

---

## 2. 一手数据全貌（2026-06-20 实测确认值）

源目录：`ai-self-evolution/skillbrew/data/sources/BV1UpR9BBEf5/`

### 2.1 plan.json（OCR 纠错叙事来源 —— 目前 record.py 还没读它！）
- `traced_sources[0]` keys = `['kind','url','name','note','verified','stars_observed_at']`
- `traced_sources[0].note`（完整纠错叙事，可整段引用）：
  > 溯源一手核实✅：仓库 mattpocock/skills（⭐136745〔2026-06-20T05:29:38 取数〕，默认分支 main）。草稿 OCR 误记为 mattpockock/claude-skills（404），经 GitHub 搜索 + 内容校验（树含 grill-me/tdd）定位真身。全仓 34 个 skill 详见 install_list.json。
- `_verify` keys = `['verified_at','verified_repo','stars','stars_observed_at','default_branch','how_resolved','skill_total','install_list','corrections','note']`
- `_verify.how_resolved` = `"草稿 repo mattpocock/skills 直查命中"`
- `_verify.corrections`（list，结构化）：
  - `"summary: OCR 错误仓库名/星数 → 一手核实纠正（含 stars_observed_at）"`
  - `"capability 'GrillMe：需求澄清追问技能': install_steps 人话→机器（skills/productivity/grill-me, 1 文件）"`
  - `"capability 'TDD红绿重构循环技能': install_steps 人话→机器（skills/engineering/tdd, 4 文件）"`
  - `"open_questions: 2/5 条用一手数据回填标注"`
- **关键**：OCR 误记的具体值（仓库名 `mattpockock/claude-skills`、星数 `81.6k`）**只存在于 note 的自然语言里**，没有结构化字段。→ 数据驱动方案见 §5.2。

### 2.2 install_list.json
- `verified_repo.full_name` = `mattpocock/skills`
- `verified_repo.stars` = `136745`，`stars_observed_at` = `2026-06-20T05:29:38`
- `verified_repo.how_resolved` = `草稿 repo mattpocock/skills 直查命中`
- `total` = `34`，`skills` count = 34
- （record.py 的 `g` 已读这些 → `full_name` / `html_url` / `how_resolved` / `star_tag` / `total` 都已就绪 ✅）

### 2.3 dedup.json
- `baseline.skill_dirs` = `["/root/.claude/skills", "/root/.coze/agents/7648652962088370459/workspace/.claude/skills"]`
- `baseline.counts` = `{distinct:41, disk_entries:41, registry_rows:41, by_status:{active:40, merged:1}}`
  （这是 dedup 跑时的基准 = 代码 install 之前；现在已装 13 个，故当前 active=53）
- `summary` = `{new:15, merge:3, skip:16, total:34}`
- `decisions` 按 verdict：skip=16 / new=15 / merge=3
- skip 的 `reason` 字段含「已装：…」或「已整并进 Python测试技能」前缀，可用于区分「手动A已装」vs「tdd已整并」

### 2.4 registry.db（台账）
- `skills` 表：active=**53**，merged=**1**（合计 distinct=54）
- `install_sessions` 表（本源 BV1UpR9BBEf5 共 2 条）：

| id | source_video | authorization_choice | before | added | merged | after | installed_at |
|----|--------------|----------------------|--------|-------|--------|-------|--------------|
| 1 | BV1UpR9BBEf5 | A（手动） | 25 | 15 | 1 | 40 | 2026-06-20T02:00:12 |
| 2 | BV1UpR9BBEf5 | install --approve（代码） | 41 | 13 | 0 | 54 | 2026-06-20T05:32:20 |

### 2.5 口径陷阱（诚实注必须保留！）
两次会话的 before/after **口径不同**：
- 会话1（手动 A）：after=**40 按 active 计**（merged 的 tdd 不计入 after=40）
- 会话2（代码 --approve）：before=**41**（= dedup 基准 distinct，含 merged）/ after=**54 按 distinct 计**（含 merged）
- 最终台账统一口径：distinct = **54** = active 53 + merged 1
- 推导关系：dedup 基准 distinct=41 == 会话2 before=41 ✅；会话1 after=40（active口径）≠ 41（distinct口径）→ 这正是口径差异来源。
- record.py 现有 lines 255-258 的诚实注解释这点，**改造时必须保留**（可数据驱动化措辞，但口径差异这件事不能删）。

---

## 3. record.py 当前精确状态

文件：`ai-self-evolution/skillbrew/skillbrew/record.py`

### 3.1 ✅ 已完成（勿动）
- **辅助函数**（lines 117-169，今天新加）：
  - `_session_label(i, choice)` → `①手动 A` / `②代码 --approve` / `③{choice}`
  - `_session_arrows(sessions)` → 一行文字累加轨迹，全从 sessions 现取
  - `_cumulative_flow(sessions, active, merged)` → before/added/merged/after 累加 Mermaid 图，全从 sessions 现取；末个会话节点附 `{len(active)} active+{len(merged)} merged` 细分；返回 Mermaid 行（**不含** ```fence）
  - 这三个函数**已实现、已可用**，但生成器里还没调用它们。
- **`skill_dirs` 默认口径 bug 已修**（lines 477-484）：默认读 `dedup.json` 的 `baseline.skill_dirs`，保证落盘核对与去重基准同口径。
- `_gather()`（lines 55-106）已读 install_list.json + dedup.json + registry.db + 扫磁盘；返回的 `g` dict 含 `full_name/html_url/how_resolved/star_tag/total/all_skills/active/merged/src_sessions/disk_distinct/orphans/missing/new_installed/new_deprecated/merge_cands/skips/summary/skill_dirs` 等。
- `record()` 主函数（lines 463-513）+ `_main()`（lines 517+）可独立 `python -m skillbrew.record <src>` 跑。

### 3.2 ❌ 未完成（明天从这里动手）

#### A. RECORD §5 硬编码 Mermaid（lines 291-301）
现状（写死 25/40/54）：
```python
L.append("```mermaid")
L.append("flowchart LR")
L.append('    B0["起步<br/>25 distinct"] -->|"+15 新 +1 整并"| B1["①手动 A<br/>40 active"]')
L.append('    B1 -->|"+13 新"| B2["②代码 --approve<br/>54 distinct<br/>(53 active+1 merged)"]')
L.append("    classDef s fill:#e8f0fd,stroke:#2c6cb0;")
L.append("    classDef e fill:#e8f8e8,stroke:#27ae60;")
L.append("    class B0,B1 s;")
L.append("    class B2 e;")
L.append("```\n")
```
**改法**：用 `_cumulative_flow` 替换（它已生成全部 Mermaid 行，含 classDef/class）：
```python
L.append("```mermaid")
L.extend(_cumulative_flow(g["src_sessions"], active, merged))
L.append("```\n")
```

#### B. DASHBOARD §0 一句话硬编码（lines 350-352）
现状写死 `mattpocock/skills`、`25 → 40 → 54`、`mattpockock`。
**改法**：
- 仓库名用 `g["full_name"]`（已有）
- 累加轨迹用 `_session_arrows(g["src_sessions"])` 替换 `25 → 40（手动 A）→ 54（代码 --approve）`

#### C. DASHBOARD §1 顺藤摸瓜追踪图硬编码（lines 355-370）
现状写死 `BV1UpR9BBEf5`、`mattpockock/claude-skills`、`mattpocock/skills`、`81.6k`、`25 → 40`、`41 → 54`、`54 distinct`。
**改法**（见 §5.2 设计决策）：
- 素材节点用 `g["source_dir"].name`
- 会话节点 before/after 用 sessions 现取（`_session_arrows` 或逐个取）
- OCR 误记的具体错值（`mattpockock/claude-skills` / `81.6k`）无结构化字段 → **正文直接引用 `plan.json` 的 note 全文**；Mermaid 节点改用 `_verify.corrections[0]` 文本（"OCR 错误仓库名/星数 → 一手核实纠正"），不写死具体名字。

#### D. DASHBOARD §4 累加可视化硬编码（lines 400-409）
现状写死 `25`/`40`/`54`/`53 active+1 merged`。
**改法**：同 A，用 `_cumulative_flow(g["src_sessions"], active, merged)` 替换 lines 401-409 的 Mermaid 块。

#### E. `_gather()` 没读 plan.json（lines 55-106）
**必须加**：读 `source_dir/plan.json`，提取 OCR 纠错叙事，塞进 `g`：
```python
plan = json.loads((source_dir / "plan.json").read_text(encoding="utf-8")) if (source_dir / "plan.json").exists() else {}
verify_blk = plan.get("_verify", {})
traced = plan.get("traced_sources", [])
# 塞进返回 dict：
"plan": plan,
"ocr_note": (traced[0].get("note", "") if traced else "") or verify_blk.get("note", ""),
"verify_how": verify_blk.get("how_resolved", ""),
"verify_corrections": verify_blk.get("corrections", []),
```
然后 DASHBOARD §1 正文用 `g["ocr_note"]`，Mermaid 用 `g["verify_corrections"]`。

#### F. RECORD §6 回滚段硬编码（line 310）
现状写死「手动 A 装的 15 个」。**改法**：从 sessions 算 —— 会话1 added=15，或 `g["src_sessions"][0]["skills_added"]`。改成 `会话1（手动）装的 {g['src_sessions'][0]['skills_added']} 个`（前提：有会话）。

#### G. DASHBOARD §2 skip 明细硬编码（line 381）
现状写死「手动 A 已装 15 个 + tdd 已整并 1 个 = 16」。**改法**：从 skips 的 reason 分类计数（reason 含「已整并」的算整并，其余算已装），或直接用 `len(g["skips"])` + 会话1 的 added/merged。优先从 dedup decisions 的 reason 字段现取，不写死 15/1。

---

## 4. CLI 接入（明天要做的第二件事）

文件：`ai-self-evolution/skillbrew/skillbrew/cli.py`
现状：**没有 `record` 子命令**（已确认，cmd_install/p_inst 在 lines 372-492，其后直接 main()）。

照 `cmd_install` / `p_inst` 模式加：

```python
def cmd_record(args: argparse.Namespace) -> int:
    """记录+看板：从台账/清单/去重一手数据代码生成安装记录与看板（只读，不改台账）。"""
    from . import record as record_mod

    cfg = load_config()  # 校验配置 + 路径解析一致（record 不用 LLM，纯只读）
    src = _resolve_source(cfg, args.source)
    if not (src / "install_list.json").exists():
        print(f"[ERR] {src} 没有 install_list.json（先跑 verify）")
        return 1
    if not (src / "dedup.json").exists():
        print(f"[ERR] {src} 没有 dedup.json（先跑 dedup）")
        return 1

    # skill_dirs：默认读 dedup.json 的 baseline.skill_dirs（与去重同口径）；--skills-dir 可追加
    skill_dirs = None
    if args.skills_dir:
        # 用户追加目录 → 用追加的 + 默认两个；或直接全交给 record 默认逻辑 + 追加
        skill_dirs = [Path(d) for d in args.skills_dir]

    print(f"[记录+看板] {src}")

    def on_progress(stage: str, n) -> None:
        if stage == "read":
            print(f"   扫描磁盘目录：{[str(d) for d in (n or [])]}")
        elif stage == "write":
            print("   生成 RECORD.md + DASHBOARD.md ...")

    try:
        r = record_mod.record(src, skill_dirs=skill_dirs, on_progress=on_progress)
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] 记录失败：{e}")
        return 2

    ig = r["integrity"]
    print("\n" + "=" * 60)
    print(f"✅ 代码生成完成：仓库 {r['verified_repo']}")
    print(f"   本源安装会话：{r['sessions']} 次；本次新装 {len(r['this_run_installed'])} 个")
    print(f"   落盘核对：磁盘 {ig['disk_active_distinct']} == 台账 {ig['registry_active']}"
          f" → {'✅一致' if ig['ok'] else '⚠️不一致'}")
    if ig["orphans"]:
        print(f"   孤儿（磁盘有/台账无）：{ig['orphans']}")
    if ig["missing"]:
        print(f"   缺失（台账有/磁盘无）：{ig['missing']}")
    print(f"   记录 → {r['record_path']}")
    print(f"   看板 → {r['dashboard_path']}")
    print("=" * 60)
    print("刹车：record 只读，未改台账、未下载、未调 LLM。")
    return 0
```

注册子命令（紧跟 `p_inst` 之后，lines 492 后）：
```python
p_rec = sub.add_parser(
    "record",
    help="记录+看板：从台账/清单/去重一手数据代码生成安装记录与看板（只读，不改台账）",
)
p_rec.add_argument("source", help="源目录 或 B站URL/BV号")
p_rec.add_argument(
    "--skills-dir", action="append", default=None, metavar="DIR",
    help="追加扫描目录（默认读 dedup.json 的 baseline.skill_dirs，与去重同口径）",
)
p_rec.set_defaults(func=cmd_record)
```

注意 `--skills-dir` 语义：record 默认读 dedup 的 skill_dirs（已修好），用户传 `--skills-dir` 是**追加**。实现上：若用户传了，应 = dedup 默认目录 + 追加目录（避免漏扫默认两个）。上面的草案只用了追加目录，明天定稿时改成「默认两个 + 追加」更安全。参考 `cmd_dedup`（lines 340）的写法：`[Path.home()/".claude"/"skills"] + [Path(d) for d in args.skills_dir]`，但 record 的默认来自 dedup.json 而非硬编码 home，需协调。

---

## 5. 设计决策（明天定稿前想清楚）

### 5.1 OCR 误记值如何数据驱动
`mattpockock/claude-skills`（错仓库名）和 `81.6k`（错星数）只在 `plan.json` 的 note 自然语言里。
- **方案A（推荐）**：正文整段引用 `g["ocr_note"]`（note 已是完整纠错叙事，含错值+纠正值+时点）；Mermaid 节点不写死具体错值，用 `g["verify_corrections"][0]` 的描述文本。→ 完全数据驱动，无需解析自然语言，最稳。
- 方案B：正则解析 note 提取错仓库名/错星数 —— 脆，不推荐。
- **结论**：走 A。DASHBOARD §1 正文 = `g["ocr_note"]`；Mermaid「OCR 误记」节点文字 = `g["verify_corrections"][0]`（若无 corrections 则降级为"草稿 OCR 误记 → 一手纠正"）。

### 5.2 RECORD §5 / DASHBOARD §4 用同一个 `_cumulative_flow`
两处都是 before/after 累加图，复用同一函数。注意 `_cumulative_flow` 返回的是**不含 fence 的行列表**，调用方负责包 ```mermaid ... ```。

### 5.3 保留诚实注
RECORD §2（lines 255-258）的 before/after 口径差异注、DASHBOARD §6（lines 442-456）的「代码不判是否值得装」诚实提示 —— **改造时保留**，可让措辞数据驱动化，但「口径不同」「不判价值」这两个诚实点不能删。

---

## 6. 跑生成 + 验证（明天要做的第三件事）

```bash
cd /root/.coze/agents/7648652962088370459/workspace/ai-self-evolution/skillbrew
python -m skillbrew record BV1UpR9BBEf5
```

**验证标准**（全部要满足）：
- `integrity.ok` = True
- `sessions` = 2
- `this_run_installed` 长度 = 13
- 磁盘 active distinct = 53 == 台账 active = 53
- `orphans` = [] 且 `missing` = []
- RECORD.md / DASHBOARD.md 里**搜不到**这些硬编码字面量（grep 验证）：
  - `25 distinct` / `40 active` / `54 distinct`（应改成现取）
  - `mattpockock/claude-skills`（应来自 note，非硬编码到代码）
  - `81.6k`
  - `BV1UpR9BBEf5` 在 Mermaid 节点里硬编码（应来自 source_dir.name）
- 累加图节点数字 = sessions 实际值（25→40→54，但来自数据而非字面量）

验证后：
```bash
# 顺便确认旧的手写产物还在（代码生成不覆盖它们，留对照）
ls data/sources/BV1UpR9BBEf5/  # 应同时有 RECORD.md DASHBOARD.md POST_INSTALL.md REPORT.md
```

---

## 7. 收尾（已完成 ✅）

- ✅ **PROJECT_CHARTER.md 加 r19 修订记录**（newest-first，r18 上方）：详记 Step 5 record+看板代码生成完成、数据驱动（方案A）、CLI `record` 子命令、`--skills-dir` 追加语义、3 个辅助函数、零硬编码验证、刹车只读、诚实注保留。
- ✅ **幂等回归通过**：重跑 `record` 两份产物字节级一致。
- ✅ **记忆更新**：`skillbrew-step5-handoff` 已更新为「已完成」+ r20 入口。

### 7.1 任务列表对账（TaskUpdate 工具在当前 harness 吞参数 → 禁用，状态以本文为准）

当前任务工具列表（系统 reminder 实测可见）与真实进度对账：

| # | 任务标题（reminder 显示） | 列表状态 | 真实状态 | 依据 |
|---|------|------|------|------|
| #4-#15 | Coze skill 文档/入口系列 | completed | ✅ completed | 一致，不动 |
| #16 | 拆分 .env/.env.example 为 TEXT/VISION 两组配置 | pending | ✅ 应为 completed | LLM 分工 TEXT=DeepSeek/VISION=Agnes 已落地（章程 D18） |
| #17 | 章程 D13 转 ✅已定 + r10 修订记录 + 记忆更新 | pending | ✅ 应为 completed | charter 有 r10（newest-first 在 r11+ 之下） |
| #18 | 搭 skillbrew 骨架（config + 可插拔 LLM + cli doctor） | pending | ✅ 应为 completed | skillbrew 包已存在 config/cli/registry |
| #19 | MVP-3 消化：DeepSeek 融合字幕+关键帧→执行计划 | pending | ✅ 应为 completed | run/ingest/understand（r15） |
| #20 | MVP-4 审核门：计划→Markdown 人工授权 | pending | ✅ 应为 completed | plan 停刹车（r15） |
| #21 | MVP-5 安装+台账+报告 | pending | ✅ 应为 completed | install+registry+record（r18/r19） |
| #22 | 提炼 inline 脚本为 skillbrew 模块(ingest/understand) | pending | ✅ 应为 completed | r15 |
| #23 | Step 2: verify 溯源模块 | pending | ✅ 应为 completed | r16 |
| #24 | Step 3: dedup 去重模块 | pending | ✅ 应为 completed | r17 |
| #25 | Step 4: install + registry 接 CLI | pending | ✅ 应为 completed | r18 |
| #26 | Step 5: record + dashboard | pending | ✅ 应为 completed | r19（本 HANDOFF 主题，已验证） |
| #27 | 回归测试：重跑 BV1UpR9BBEf5 验证结果匹配手工跑 | pending | ✅ 应为 completed（via Path A 新源） | 原"重跑原源"被 Path A 取代（规避 dedup 覆盖历史风险）；新源 BV1Kj9zBWEjS 全链路 run→verify→dedup→install(dry)→record 跑通，见「✅ r20 完成总结」 |

> 因 TaskUpdate 不可用，上表为权威对账。若日后 TaskUpdate 恢复（重试一次验证 taskId 是否仍被吞），可据此表批量回标；否则继续以本文为准。#16-#24 标「应为 completed」是基于章程 r10-r19 修订记录推断，r20 回归时抽验确认即可，不阻塞推进。

---

## 8. 安全约束（始终有效，别忘了）

- 推 GitHub 前**必须**在平台控制台重新生成 DeepSeek 和 Agnes 的 key。
- `.env` 保持 gitignored，**禁止**提交或日志打印任何 key。
- record 是只读命令，理论上不碰 key —— 但跑回归测试时若涉及 run/ingest 会用到，注意别在日志/提交里泄露。

---

## 9. 明天的起手式（建议顺序）

1. 读本 HANDOFF + 记忆 `skillbrew-step5-handoff` → 重建上下文。
2. `cd ai-self-evolution/skillbrew`，`python -c "from skillbrew import record, cli"` 确认导入正常。
3. 按 §3.2 A→G 顺序改 record.py（先 E 加 plan.json 读取，再 A/D/B/C/F/G 替换硬编码）。
4. 按 §4 接 CLI record 子命令。
5. 按 §6 跑生成 + grep 验证无硬编码 + integrity ok。
6. 按 §7 补 PROJECT_CHARTER r19 + 清任务列表 + 更新记忆。

卡点的精确坐标：**`record.py` lines 291-301（RECORD §5）和 lines 348-429（DASHBOARD §0/§1/§4）的硬编码段 + `_gather` lines 55-106 没读 plan.json**。辅助函数 `_cumulative_flow`/`_session_label`/`_session_arrows`（lines 117-169）已就绪可直接调用。从这里接上线即可。
