# 贡献指南

## 开发流程

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 跑测试
pytest -q

# 跑文档同步守卫（CI 也会跑）
python scripts/check_docs_sync.py --check
```

## 文档同步纪律（D-doc-sync）

仓库里有三份面向用户的文档，里面有一些**核心锚点事实**是重复出现的。改了一处必须三处都改，否则 CI 会红：

| 文件 | 角色 |
|---|---|
| `README.md` | GitHub 仓库首页，最全的用户入口 |
| `PROJECT_CHARTER.md` | 项目章程，记录架构决策与边界 |
| `docs/index.html` | GitHub Pages 落地页 |

### 必须三处同步的锚点事实

1. **管线步数**：永远是"8 步"（采集→理解→消化→溯源→判断→去重→安装→记录）。如果以后加/删步骤，必须三处一起改，并且更新本文件的表。
2. **已装 MCP 清单**：`playwright` / `filesystem` / `sequential-thinking` / `context7` / `github`。新增或移除一个 MCP 时，README 的"MCP 服务器"表、CHARTER §9 的已装清单必须同步更新。
3. **暂缓项**：当前是 `memos MCP`（无官方 npm 包）和 `MoneyPrinterTurbo`（需 `OPENAI_API_KEY`）。如果其中一个被装了或者新增暂缓项，README 的"暂缓项"段、docs/index.html 的状态区必须同步改。

### docs/index.html 故意不硬编码的内容

落地页不硬编码详细 MCP 清单（写"具体清单和调用方式以本地 `RECORD.md` 台账为准"），避免每次装新 MCP 都要改 HTML。但它**必须**出现足够多的 MCP 名字暗示真实范围（至少 3 个），否则 `check_docs_sync.py` 会报错。

### 同步守卫脚本

`scripts/check_docs_sync.py` 做轻量校验：
- 无参数运行：只打印信息，不拦流程。
- `--check`：发现漂移就退出非零，CI 用这个。

脚本**不**做全文逐字比对——文案措辞差异是允许的，它只盯着上面列出的锚点事实。如果你确认改的就是锚点事实本身（例如真的加了第 9 步），需要：
1. 三处都改；
2. 更新本小节的锚点清单；
3. 更新 `scripts/check_docs_sync.py` 里的常量。

## 提交前自检清单

- [ ] `pytest -q` 全绿
- [ ] `python scripts/check_docs_sync.py --check` 通过
- [ ] 改了公开文档（README/CHARTER/docs/）的话，确认锚点事实三处一致
- [ ] 推前在暂存区 grep 一遍密钥指纹（`sk-` / `ghp_` / `github_pat_` / `Bearer ` / `AKIA` / `xox` / agent_id `7648652962088370459`），0 命中才能 push
- [ ] 推后 fresh-clone 再扫一次（仓库是 PUBLIC，零容忍漏 key）

## 哪些文件**不要**放进仓库

- `.env`（已 `.gitignore`）——只放 `.env.example` 占位
- `*.private.md` / `.handoff/`（已 `.gitignore`）——内部笔记、自我交接
- 任何包含真实 API key / PAT / cookie 的文件

## 分支与推送

- 直接在 `main` 上提交；本项目目前是单人维护，不开 feature branch 流程。
- 每个提交做一件事，commit message 中文说清楚改了什么。
- 远端：`origin = https://github.com/Rookage/skillbrew.git`（**PUBLIC**，全球可读）。
