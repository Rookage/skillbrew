"""verify：溯源 —— 回 GitHub 取一手资料，纠正草稿计划里的 OCR 猜测。

plan.json（消化草稿）只看视频画面 + 字幕，画面里的仓库名/星数是 OCR 抓的，
容易错（本例就把 mattpocock 看成 mattpockock、把 skills 看成 claude-skills）。
verify 不靠猜：直接 curl 到 GitHub，拿一手事实，回填纠正 plan.json，并产出
一份"机器可执行安装清单" install_list.json —— 后面 install 模块照着这个清单
逐项整目录拷即可，无需人读。

三条 GitHub 取数路径（章程 5.3，本环境实测可通，公开仓无需鉴权、不耗 LLM 配额）：
  ① /repos/{owner}/{repo}            核实仓库存在 + 星数 + 默认分支
  ② /repos/{o}/{r}/git/trees/{branch}?recursive=1   拉全文件树（列全部 SKILL.md）
  ③ raw.githubusercontent.com/{o}/{r}/{branch}/{path}  按【完整树路径】取文件正文
     （raw 不耗 API 限额；路径必须用 git/trees 返回的完整路径，不能猜短路径）

仓库名怎么从"错的草稿"找回"对的真身"（不硬编码）：
  1) 先直查草稿里写的 repo（traced_sources 的 github URL）—— 多半 404（OCR 错）；
  2) 404 则拿草稿 repo 名当种子，GitHub 搜仓库 + 按星数排，取前若干候选；
     候选再按仓库体积升序排（小仓库先查、快），逐个拉文件树；
  3) 校验"候选树里是否含草稿点名的 skill（如 grill-me/tdd）"——只有真含同名
     SKILL.md 的候选才算命中（一手内容校验，防搜到同名高分但内容不符的仓库）；
  4) 都不命中 → 报错让用户 --repo 指定。

刻舟求剑（章程 5.3）：星数是动态线索非定值，必标 stars_observed_at。
一个 skill = 它的整个目录（tdd 是多文件：SKILL.md + mocking.md + ...），install_list
每项记目录树路径 + 目录下全部文件，install 时整目录拷。
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from pathlib import Path

from . import mcp_catalog, ratelimit
from ._utils import _now_iso

logger = logging.getLogger(__name__)

API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
UA = "skillbrew"  # GitHub 要求带 User-Agent，否则 403
SKILL_MD = "SKILL.md"
_TIMEOUT = 30.0
_SEARCH_CANDIDATES = 8  # 搜索取前 N 个候选再逐个校验
_MAX_RETRIES = 3  # 5xx/网络瞬时错误重试次数（git/trees 端点偶发 504）
_RETRY_BACKOFF = 2.0  # 退避基数秒：第 n 次重试睡 n*BACKOFF 秒


def _get(
    url: str, *, accept: str = "application/vnd.github+json", timeout: float = _TIMEOUT
) -> tuple[int, bytes]:
    """发请求；5xx 与网络瞬时错误自动退避重试（git/trees 端点偶发 504，重试通常即通）。

    4xx（404/403 限速等）不重试，原样返回 (code, body) 交调用方判断。
    发请求前先过 ratelimit 令牌桶（search/core 分桶），主动节流尽量不撞 403；
    收到响应（成功或 HTTPError）后用 X-RateLimit-* 头同步本地桶，避免估算漂移。
    """
    ratelimit.acquire_for_url(url)
    for attempt in range(_MAX_RETRIES):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                ratelimit.update_from_headers(url, r.headers)
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            ratelimit.update_from_headers(url, e.headers)
            if 500 <= e.code < 600 and attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BACKOFF * (attempt + 1))
                continue  # 5xx 网关瞬时错误，退避后重试
            return e.code, e.read()  # 4xx 或重试用尽，原样返回
        except urllib.error.URLError as e:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BACKOFF * (attempt + 1))
                continue  # 网络抖动，重试
            raise RuntimeError(f"网络请求失败 {url}: {e}") from e
    raise RuntimeError(f"请求重试用尽 {url}")  # _MAX_RETRIES=0 时兜底


def _api_json(url: str) -> dict:
    status, body = _get(url)
    if status == 403:
        # GitHub API 限流，fallback 到 gh CLI（已认证，限流更宽松）
        return _gh_cli_fallback(url)
    if status != 200:
        raise RuntimeError(f"GitHub API {status} {url}: {body[:200]!r}")
    return json.loads(body)


def _gh_cli_fallback(url: str) -> dict:
    """当 GitHub API 403 限流时，用 gh CLI 替代（已认证，5000 次/小时）。

    支持的 URL 模式：
    - /repos/{owner}/{repo} → gh repo view owner/repo --json ...
    - /repos/{owner}/{repo}/git/trees/{branch}?recursive=1 → gh api ...
    """
    # 解析 URL 提取 owner/repo/branch
    m = re.match(rf"{re.escape(API_BASE)}/repos/([^/]+)/([^/]+)(?:/git/trees/([^?]+))?", url)
    if not m:
        raise RuntimeError(f"gh CLI fallback 不支持的 URL 模式: {url}")

    owner, repo = m.group(1), m.group(2)
    branch = m.group(3)

    try:
        if branch:
            # /repos/{owner}/{repo}/git/trees/{branch}?recursive=1
            endpoint = f"/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
            result = subprocess.run(
                ["gh", "api", endpoint], capture_output=True, text=True, timeout=_TIMEOUT
            )
        else:
            # /repos/{owner}/{repo}
            result = subprocess.run(
                [
                    "gh",
                    "repo",
                    "view",
                    f"{owner}/{repo}",
                    "--json",
                    "nameWithOwner,url,stargazerCount,defaultBranchRef,description,pushedAt",
                ],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT,
            )

        if result.returncode != 0:
            raise RuntimeError(f"gh CLI 失败: {result.stderr[:200]}")

        data = json.loads(result.stdout)

        # 统一字段名（gh repo view 使用 GraphQL 风格字段名，转回 REST API 风格）
        if "nameWithOwner" in data:
            data["full_name"] = data.pop("nameWithOwner")
        if "url" in data:
            data["html_url"] = data.pop("url")
        if "stargazerCount" in data:
            data["stargazers_count"] = data.pop("stargazerCount")
        if "defaultBranchRef" in data and isinstance(data["defaultBranchRef"], dict):
            data["default_branch"] = data["defaultBranchRef"]["name"]
            del data["defaultBranchRef"]
        if "pushedAt" in data:
            data["pushed_at"] = data.pop("pushedAt")

        return data

    except FileNotFoundError:
        raise RuntimeError("gh CLI 未安装或不在 PATH 中，无法 fallback")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"gh CLI 超时（{_TIMEOUT}s）")


def _raw_text(url: str) -> str:
    status, body = _get(url, accept="text/plain")
    if status != 200:
        raise RuntimeError(f"raw {status} {url}")
    return body.decode("utf-8", errors="replace")


# ---- 仓库名解析 / 核实 ----

# owner/repo 限定 GitHub 官方字符集（[A-Za-z0-9-] / [A-Za-z0-9._-]），用 lookahead 锚尾——
# 否则 URL 后紧跟中文 prose（如「…/claude-code-templates或其…」）会被原非贪婪组吃进 repo 名，
# 导致 probe_repo 拼出含中文的 URL、urlopen 内部 ascii 编码炸（UnicodeEncodeError，非 RuntimeError，
# 穿透 except RuntimeError）。lookahead 在首个非仓库名字符（含中文）处收口，repo 即停在「或」前。
_GH_URL_RE = re.compile(
    r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]*))/([A-Za-z0-9._-]+)(?=[^A-Za-z0-9._-]|$)"
)


def parse_github_urls(text: str) -> list[tuple[str, str]]:
    """从任意文本里抠 github.com/{owner}/{repo}，去重，去 .git 后缀。"""
    seen, out = set(), []
    for m in _GH_URL_RE.finditer(text):
        owner, repo = m.group(1), m.group(2)
        repo = re.sub(r"\.git$", "", repo)
        if "." in repo:  # 排除 github.com/owner/xxx.png 之类
            continue
        key = (owner.lower(), repo.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append((owner, repo))
    return out


def probe_repo(owner: str, repo: str) -> dict | None:
    """核实仓库存在：返回 full_name/stars/default_branch/description；404 返回 None。"""
    try:
        d = _api_json(f"{API_BASE}/repos/{owner}/{repo}")
    except RuntimeError as e:
        if " 404 " in str(e):
            return None
        raise
    return {
        "owner": owner,
        "repo": repo,
        "full_name": d.get("full_name"),
        "html_url": d.get("html_url"),
        "stars": d.get("stargazers_count"),
        "default_branch": d.get("default_branch", "main"),
        "description": d.get("description"),
        "pushed_at": d.get("pushed_at"),
    }


def list_tree(owner: str, repo: str, branch: str) -> list[dict]:
    """拉全文件树（recursive），返回 [{path, type, size}]。截断则抛错（本场景不应截断）。"""
    url = f"{API_BASE}/repos/{owner}/{repo}/git/trees/{urllib.parse.quote(branch)}?recursive=1"
    d = _api_json(url)
    if d.get("truncated"):
        raise RuntimeError(f"文件树被截断（仓库过大），无法可靠校验：{owner}/{repo}")
    return [
        {"path": t["path"], "type": t["type"], "size": t.get("size", 0)} for t in d.get("tree", [])
    ]


def group_skill_dirs(tree: list[dict]) -> list[dict]:
    """把树里所有 SKILL.md 按其所在目录归组成 skill。

    支持 skills/<category>/<name>/SKILL.md（本仓结构）与平铺 <name>/SKILL.md。
    每个 skill = 该目录下全部文件（含伴随文件，如 tdd 的 mocking.md 等）。
    返回 [{category, name, dir_path, sk_md_path, files, file_count, multi_file}]。
    """
    by_dir: dict[str, dict] = {}
    # 第一遍：用 SKILL.md 定位每个 skill 目录
    for t in tree:
        p = t["path"]
        if not p.endswith("/" + SKILL_MD):
            continue
        parts = p.split("/")
        if len(parts) >= 4 and parts[0] == "skills" and parts[-1] == SKILL_MD:
            category, name = parts[1], parts[2]
        elif len(parts) >= 2 and parts[-1] == SKILL_MD:
            category, name = "(root)", parts[-2]
        else:
            continue
        dir_path = "/".join(parts[:-1])
        by_dir[dir_path] = {
            "category": category,
            "name": name,
            "dir_path": dir_path,
            "sk_md_path": p,
            "files": {},
        }
    # 第二遍：把每个 skill 目录下的全部文件归入（整目录，只收 blob 文件，跳过子目录树节点）
    for t in tree:
        if (
            t.get("type") != "blob"
        ):  # 跳过 tree（子目录）/commit 节点，只收文件，否则 raw_url 会 404
            continue
        p = t["path"]
        for dir_path, d in by_dir.items():
            if p.startswith(dir_path + "/"):
                d["files"][p] = {"path": p, "size": t.get("size", 0)}
                break
    out = []
    for d in by_dir.values():
        files = sorted(d["files"].values(), key=lambda f: f["path"])
        out.append(
            {
                "category": d["category"],
                "name": d["name"],
                "dir_path": d["dir_path"],
                "sk_md_path": d["sk_md_path"],
                "files": files,
                "file_count": len(files),
                "multi_file": len(files) > 1,
            }
        )
    out.sort(key=lambda x: (x["category"], x["name"]))
    return out


# ===================== MCP（模型上下文协议）形态 =====================
# 章程 D2：产物形态由计划内容决定，不预设。下面这条链处理 form=="MCP" 的能力：
#   plan.capabilities 的 source_ref 索引 traced_sources 取 MCP 服务器名
#   → mcp_catalog（brew-formula 硬编码表，D20）查命中/未命中
#   → 命中建 install item（含注册信息 + usability + 装完前必做），未命中进 unresolved 透明降级
# 不走 resolve_repo（那是单仓 Skill 架构，MCP 视频常有多个不同仓，会错配）。


def group_mcp_items(plan: dict, catalog=mcp_catalog) -> tuple[list[dict], list[dict]]:
    """MCP 形态：遍历 plan.capabilities，按 source_ref 取 traced_sources 里的 MCP 名，
    查 catalog（brew-formula 表）建 install item；未命中进 unresolved。

    为什么不直接用 capability.name：capability.name 是中文能力描述（如"浏览器自动化操作
    与前端测试"），真正的 MCP 服务器名在 traced_sources[int(source_ref)-1].name（如
    "microsoft/playwright-mcp" / "File System MCP"）。source_ref 是 1 起的字符串，
    traced_sources 是 0 起数组，故 idx = int(source_ref) - 1。

    返回 (items, unresolved)。纯查表，不联网、不调 LLM、不耗配额（章程 D18）。
    """
    traced = plan.get("traced_sources", []) or []
    caps = plan.get("capabilities", []) or []
    items: list[dict] = []
    unresolved: list[dict] = []
    for cap in caps:
        if (cap.get("form") or "").upper() != "MCP":
            continue
        source_ref = cap.get("source_ref")
        raw_name = ""
        idx = -1
        if source_ref is not None:
            try:
                idx = int(source_ref) - 1
            except (TypeError, ValueError):
                idx = -1
            if 0 <= idx < len(traced):
                raw_name = traced[idx].get("name", "") or ""
        entry = catalog.lookup(raw_name) if raw_name else None
        if entry is None:
            hint = catalog.suggest_candidate(raw_name) if raw_name else None
            unresolved_entry: dict = {
                "name": raw_name or cap.get("name", ""),
                "reason": hint["reason"]
                if hint
                else "mcp_catalog 未收录：无官方标准 MCP 包，或名称需人工核实（不臆造包装）",
                "candidate": hint["candidate"] if hint else None,
                "source_ref": source_ref,
            }
            # D23: 从 traced_source 抠 repo/url，给 AI 推断当源头（纯查表，不破 D18）
            if 0 <= idx < len(traced):
                owner_repo = _ts_repo(traced[idx])
                if owner_repo:
                    unresolved_entry["repo"] = f"{owner_repo[0]}/{owner_repo[1]}"
                    unresolved_entry["url"] = f"https://github.com/{owner_repo[0]}/{owner_repo[1]}"
            unresolved.append(unresolved_entry)
            continue
        # 防御：catalog 条目 command 为空时当 unresolved 处理（不产出无效 item）
        if not entry.command:
            unresolved.append(
                {
                    "name": entry.name,
                    "reason": "catalog 条目 command 为空，无法安装",
                    "candidate": None,
                    "source_ref": source_ref,
                    "repo": entry.repo,
                    "url": entry.url,
                }
            )
            continue
        items.append(
            {
                "name": entry.name,
                "form": "MCP",
                "install_method": "mcp_register",
                "mcp": {
                    "transport": entry.transport,
                    "command": entry.command,
                    "args": list(entry.args),
                    "scope": entry.scope_hint,
                },
                "repo": entry.repo,
                "url": entry.url,
                "stars": None,  # 由 _probe_stars_for_items 探一手星数后回填（刻舟求剑）
                "stars_observed_at": None,
                "usability": catalog.usability_of(entry),
                "credential_env": list(entry.credential_env) if entry.credential_env else None,
                "env_template": dict(entry.env_template) if entry.env_template else {},
                "post_install_steps": list(entry.post_install_steps)
                if entry.post_install_steps
                else [],
                "invoke_hint": entry.invoke_hint,
                "source_ref": source_ref,
                "capability_name": cap.get("name", ""),  # 中文能力描述，台账/报告展示用
            }
        )
    return items, unresolved


def _probe_stars_for_items(items: list[dict]) -> None:
    """对 items 里每个唯一 repo 探一手星数，回填 stars + stars_observed_at（刻舟求剑 §5.3）。

    catalog 本身已是 brew-formula 真相（verified=True），星数仅作参考线索，故失败（404/
    网络）留 None，不臆造。同 repo 只探一次（如 modelcontextprotocol/servers 被 filesystem/
    sequential-thinking/github 共用，探一次给三项回填同一星数——是仓库的星数，诚实）。
    """
    cache: dict[str, dict | None] = {}
    for it in items:
        repo = it.get("repo")
        if not repo:
            continue
        if repo not in cache:
            owner, _, name = repo.partition("/")
            cache[repo] = probe_repo(owner, name) if (owner and name) else None
        info = cache[repo]
        if info:
            it["stars"] = info.get("stars")
            it["stars_observed_at"] = _now_iso()


def backfill_plan_mcp(
    plan_path: Path,
    plan: dict,
    items: list[dict],
    unresolved: list[dict],
    install_list_path: Path,
) -> list[str]:
    """MCP 形态回填 plan.json 的 _verify 块：记录解析命中的 MCP、unresolved、install_list 路径。

    与 Skill 路径的 backfill_plan 对应；MCP 不改 summary 的仓库名叙事（catalog 已是真相），
    只回填 _verify 供 record/报告取用。返回 corrections 留痕。
    """
    corrections: list[str] = []
    plan["_verify"] = {
        "verified_at": _now_iso(),
        "form": "MCP",
        "verified_mcps": [it["name"] for it in items],
        "unresolved": [
            {"name": u["name"], "reason": u["reason"], "source_ref": u["source_ref"]}
            for u in unresolved
        ],
        "item_total": len(items),
        "install_list": str(install_list_path),
        "corrections": [],  # 见下；先占位再回填，保证 corrections 字段存在
        "note": "MCP 形态：由 mcp_catalog（brew-formula 表）解析，未命中者进 unresolved 交用户定夺（D19/D22）。",
    }
    corrections.append(f"_verify: MCP 形态回填（{len(items)} 命中 / {len(unresolved)} unresolved）")
    plan["_verify"]["corrections"] = corrections
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return corrections


def raw_url(owner: str, repo: str, branch: str, path: str) -> str:
    return f"{RAW_BASE}/{owner}/{repo}/{urllib.parse.quote(branch)}/{path}"


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def parse_frontmatter(text: str) -> dict:
    """抠 SKILL.md 顶部 YAML frontmatter 的 name/description（轻量解析，不引 yaml 依赖）。"""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip().strip("\"'")
        if k in ("name", "description"):
            out[k] = v
    return out


def enrich_with_frontmatter(
    owner: str, repo: str, branch: str, skills: list[dict], *, on_progress=None
) -> None:
    """逐个 skill 取 SKILL.md 正文，抠 frontmatter，回填 display_name/description/raw_url。"""
    total = len(skills)
    for i, s in enumerate(skills):
        if on_progress:
            on_progress(s, i, total)
        url = raw_url(owner, repo, branch, s["sk_md_path"])
        s["raw_url"] = url
        # 在相邻请求之间等 0.5s，避免 GitHub raw 端点的瞬时频率限制
        # （实测：35 个 skill 逐个拉不间隔时，远端频繁关闭连接）
        if i > 0:
            import time as _time

            _time.sleep(0.5)
        try:
            body = _raw_text(url)
            fm = parse_frontmatter(body)
            s["display_name"] = fm.get("name", s["name"])
            s["description"] = fm.get("description", "")
            s["body_chars"] = len(body)
        except RuntimeError as e:
            warnings.warn(f"SKILL.md 获取失败 {url}: {e}", stacklevel=2)
            s["display_name"] = s["name"]
            s["description"] = ""
            s["fetch_error"] = str(e)[:200]


# ---- 仓库名从"错的草稿"找回"对的真身" ----


def _norm(s: str) -> str:
    """归一化 skill 名用于比对：小写 + 去非字母数字。GrillMe→grillme, grill-me→grillme。"""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _extract_search_keywords(plan: dict) -> list[tuple[str, dict]]:
    """从 plan 的 summary/capabilities/traced_sources 提取搜索查询。

    返回 [(query, filters), ...]，其中 filters 可包含 stars_min/stars_max。
    提取策略：
    - 从 traced_sources.note 提取星数线索（如 "25k 星标"）
    - 从 summary 提取核心概念（如 "code graph", "knowledge graph"）
    - 组合成 GitHub 搜索查询 + 星数范围过滤
    """
    queries = []
    summary = plan.get("summary", "").lower()

    # 从 traced_sources 提取星数线索
    stars_min, stars_max = None, None
    for ts in plan.get("traced_sources", []):
        note = ts.get("note", "").lower()
        # 匹配 "25k 星标" / "28.7k 星" / "25000 stars" 等
        import re

        m = re.search(r"(\d+(?:\.\d+)?)\s*k?\s*(?:星|stars?)", note)
        if m:
            val = float(m.group(1))
            if "k" in note[m.start() : m.end()]:
                val *= 1000
            # 给一个范围：±30%
            stars_min = int(val * 0.7)
            stars_max = int(val * 1.3)
            break

    # 提取核心概念
    concepts = []
    if "code graph" in summary or "代码知识图谱" in summary:
        concepts.append("code graph index")
    if "knowledge graph" in summary:
        concepts.append("knowledge graph")
    if "codegraph" in summary:
        concepts.append("codegraph")

    # 组合查询
    for concept in concepts[:2]:  # 最多 2 个查询
        query = concept
        filters = {}
        if stars_min is not None:
            filters["stars_min"] = stars_min
        if stars_max is not None:
            filters["stars_max"] = stars_max
        queries.append((query, filters))

    # 如果没有提取到概念，fallback 到通用查询
    if not queries:
        queries.append(("ai coding tool", {}))

    return queries


def _cap_skill_name(cap_name: str) -> str:
    """草稿能力名 'GrillMe：需求澄清追问技能' / 'TDD红绿重构循环技能' → 取可比对的主名。"""
    nm = re.split(r"[:：]", cap_name, maxsplit=1)[0].strip()
    return nm


def resolve_repo(
    draft_repos: list[tuple[str, str]], draft_skill_names: list[str], plan: dict | None = None
) -> tuple[dict, str]:
    """找出真身仓库，返回 (probe 信息, how_resolved 说明)。不硬编码，靠内容校验。"""
    # 1) 直查草稿里写的 repo
    for owner, repo in draft_repos:
        info = probe_repo(owner, repo)
        if info:
            return info, f"草稿 repo {owner}/{repo} 直查命中"
    # 2) 搜索 + 内容校验
    seeds: list[str] = []
    seen = set()
    for _o, repo in draft_repos:  # 用草稿 repo 名当搜索种子
        if repo.lower() not in seen:
            seen.add(repo.lower())
            seeds.append(repo)

    # 3) Fallback：当 draft_repos 为空时，从 plan 的 summary/capabilities 提取关键词搜索
    search_queries: list[tuple[str, dict]] = []  # (query, filters)
    if not seeds and plan:
        search_queries = _extract_search_keywords(plan)

    if not seeds and not search_queries:
        raise RuntimeError("草稿没有 github repo 线索，无法溯源；请用 --repo owner/repo 指定")
    # 只保留长度 >= 3 的 _norm 结果（'ai' 这种太短，无法有效校验）
    targets = {_norm(n) for n in draft_skill_names if len(_norm(n)) >= 3}
    checked_any = False
    skip_reasons: list[str] = []

    # 处理普通 seeds（来自 draft_repos）
    for seed in seeds:
        q = urllib.parse.quote(seed)
        d = _api_json(
            f"{API_BASE}/search/repositories?q={q}&sort=stars&per_page={_SEARCH_CANDIDATES}"
        )
        items = d.get("items", [])
        if not targets:
            cands = sorted(items, key=lambda c: c.get("stargazers_count", 0), reverse=True)
        else:
            cands = sorted(items, key=lambda c: c.get("size", 0))

        for cand in cands:
            co, cr = cand["owner"]["login"], cand["name"]
            branch = cand.get("default_branch", "main")

            if not targets:
                info = {
                    "owner": co,
                    "repo": cr,
                    "full_name": cand["full_name"],
                    "html_url": cand["html_url"],
                    "stars": cand["stargazers_count"],
                    "default_branch": branch,
                    "description": cand.get("description"),
                    "pushed_at": cand.get("pushed_at"),
                }
                how = f"无点名 skill 可校验；搜 '{seed}' 按星数降序；取星数最高候选 {co}/{cr}（⭐{cand['stargazers_count']}）"
                return info, how

            try:
                tree = list_tree(co, cr, branch)
            except RuntimeError as e:
                # 截断/私有/空树/瞬时错误（已重试仍失败）：留痕后跳过，别静默
                logger.warning("[跳过] %s/%s: %s", co, cr, str(e)[:120])
                skip_reasons.append(f"{co}/{cr}: {str(e)[:80]}")
                continue
            checked_any = True
            skill_names = {_norm(s["name"]) for s in group_skill_dirs(tree)}
            hits = targets & skill_names
            if hits:
                info = {
                    "owner": co,
                    "repo": cr,
                    "full_name": cand["full_name"],
                    "html_url": cand["html_url"],
                    "stars": cand["stargazers_count"],
                    "default_branch": branch,
                    "description": cand.get("description"),
                    "pushed_at": cand.get("pushed_at"),
                }
                how = (
                    f"草稿 repo 404；搜 '{seed}' 按星排 + 体积升序；命中 {co}/{cr}"
                    f"（树含点名 skill: {sorted(hits)}）"
                )
                return info, how

    # 处理带过滤器的 search_queries（来自 _extract_search_keywords）
    for query, filters in search_queries:
        # 构建 GitHub 搜索查询，加上星数范围过滤
        q_parts = [query]
        if "stars_min" in filters:
            q_parts.append(f"stars:>={filters['stars_min']}")
        if "stars_max" in filters:
            q_parts.append(f"stars:<={filters['stars_max']}")
        q = urllib.parse.quote(" ".join(q_parts))
        d = _api_json(
            f"{API_BASE}/search/repositories?q={q}&sort=stars&per_page={_SEARCH_CANDIDATES}"
        )
        items = d.get("items", [])

        # 按星数降序（在星数范围内取最高的）
        cands = sorted(items, key=lambda c: c.get("stargazers_count", 0), reverse=True)

        for cand in cands:
            co, cr = cand["owner"]["login"], cand["name"]
            branch = cand.get("default_branch", "main")

            if not targets:
                info = {
                    "owner": co,
                    "repo": cr,
                    "full_name": cand["full_name"],
                    "html_url": cand["html_url"],
                    "stars": cand["stargazers_count"],
                    "default_branch": branch,
                    "description": cand.get("description"),
                    "pushed_at": cand.get("pushed_at"),
                }
                stars_range = ""
                if "stars_min" in filters or "stars_max" in filters:
                    stars_range = f"（星数范围: {filters.get('stars_min', 0)}-{filters.get('stars_max', '∞')}）"
                how = f"无点名 skill 可校验；搜 '{query}'{stars_range} 按星数降序；取候选 {co}/{cr}（⭐{cand['stargazers_count']}）"
                return info, how

            try:
                tree = list_tree(co, cr, branch)
            except RuntimeError as e:
                # 截断/私有/空树/瞬时错误（已重试仍失败）：留痕后跳过，别静默
                logger.warning("[跳过] %s/%s: %s", co, cr, str(e)[:120])
                skip_reasons.append(f"{co}/{cr}: {str(e)[:80]}")
                continue
            checked_any = True
            skill_names = {_norm(s["name"]) for s in group_skill_dirs(tree)}
            hits = targets & skill_names
            if hits:
                info = {
                    "owner": co,
                    "repo": cr,
                    "full_name": cand["full_name"],
                    "html_url": cand["html_url"],
                    "stars": cand["stargazers_count"],
                    "default_branch": branch,
                    "description": cand.get("description"),
                    "pushed_at": cand.get("pushed_at"),
                }
                how = (
                    f"草稿 repo 404；搜 '{seed}' 按星排 + 体积升序；命中 {co}/{cr}"
                    f"（树含点名 skill: {sorted(hits)}）"
                )
                return info, how
    if not checked_any:
        # 候选全部取树失败（多为 GitHub 瞬时 504）—— 没能做内容校验，不是"没找到匹配"
        raise RuntimeError(
            f"搜索 {seeds} 的候选全部取树失败（GitHub 瞬时错误居多），未做内容校验；"
            f"可稍后重试，或用 --repo owner/repo 指定。失败明细：{skip_reasons}"
        )
    raise RuntimeError(
        f"搜索 {seeds} 未找到含点名 skill {sorted(targets)} 的仓库；请用 --repo owner/repo 指定"
    )


def _match_capability_to_skill(cap_name: str, skills: list[dict]) -> dict | None:
    """把草稿能力名匹配到 install_list 里的 skill（支持 TDD红绿重构... 这类带中文后缀）。"""
    target = _norm(_cap_skill_name(cap_name))
    if not target:
        return None
    for s in skills:
        sn = _norm(s["name"])
        if sn and (sn == target or target.startswith(sn) or sn.startswith(target)):
            return s
    return None


def backfill_plan(
    plan_path: Path, plan: dict, info: dict, skills: list[dict], install_list_path: Path
) -> list[str]:
    """用一手事实就地纠正 plan.json，返回 corrections 列表（改了啥，留痕）。"""
    corrections: list[str] = []
    full = info["full_name"]
    stars = info["stars"]
    ts = info["stars_observed_at"]

    # 草稿原值（覆盖前捕获）：条件化"OCR 误记"叙事 + 实际 old→new 留痕，不写死本源字面量
    ts_list = plan.get("traced_sources", [])
    ts0 = ts_list[0] if ts_list else {}
    old_name = ts0.get("name", "")
    old_url = ts0.get("url", "")
    new_url = info["html_url"]
    repo_mismatch = bool(old_name) and _norm(old_name) != _norm(full)

    # summary：用一手事实组装；"OCR 误记"子句仅当 draft 仓库名≠真值才写（插值实际 old_name）
    cat_count = len({s.get("category", "") for s in skills if s.get("category")})
    matched_names: list[str] = []
    seen: set[str] = set()
    for c in plan.get("capabilities", []) or []:
        m = _match_capability_to_skill(c.get("name", ""), skills)
        if m and m["name"] not in seen:
            seen.add(m["name"])
            matched_names.append(m["name"])
    named_clause = f"视频点名的 {'、'.join(matched_names)} 均真实存在。" if matched_names else ""
    ocr_clause = (
        f"草稿曾因画面 OCR 误记仓库名 {old_name}，经溯源一手核实纠正。" if repo_mismatch else ""
    )
    new_sum = (
        f"这条视频介绍了 GitHub 开源项目 {full}（⭐{stars}〔{ts} 取数，星数动态非定值〕），"
        f"全仓实有 {len(skills)} 个 Claude Code skill（{cat_count} 类）。{named_clause}{ocr_clause}"
    )
    plan["summary"] = new_sum
    # corrections[0] 必为 summary：record.py 按位置取 corrections[0] 当 Mermaid 边标签（OCR 纠错），
    # 故 summary 留痕第一个 append，其余条件留痕随后，保证该不变量对所有源成立。
    corrections.append(
        "summary: OCR 错误仓库名/星数 → 一手核实纠正（含 stars_observed_at）"
        if repo_mismatch
        else "summary: 补 stars_observed_at 取数时点（星数动态非定值）"
    )

    old_title = plan.get("source_title", "")
    new_title = f"{full}（溯源核实）"
    if old_title != new_title:
        corrections.append(f"source_title: {old_title!r} → {new_title!r}")
        plan["source_title"] = new_title

    if ts_list:
        if old_url != new_url:
            corrections.append(f"traced_sources[0].url: {old_url} → {new_url}")
        ts0["url"] = new_url
        if repo_mismatch:
            corrections.append(f"traced_sources[0].name: {old_name} → {full}")
        ts0["name"] = full
        tree_hint = f"（树含 {'、'.join(matched_names)}）" if matched_names else ""
        if repo_mismatch:
            ts0["note"] = (
                f"溯源一手核实✅：仓库 {full}（⭐{stars}〔{ts} 取数〕，默认分支 {info['default_branch']}）。"
                f"草稿 OCR 误记为 {old_name}，经 GitHub 搜索 + 内容校验{tree_hint}定位真身。"
                f"全仓 {len(skills)} 个 skill 详见 install_list.json。"
            )
        else:
            ts0["note"] = (
                f"溯源一手核实✅：仓库 {full}（⭐{stars}〔{ts} 取数〕，默认分支 {info['default_branch']}）。"
                f"草稿 repo 名与一手一致{tree_hint}。"
                f"全仓 {len(skills)} 个 skill 详见 install_list.json。"
            )
        ts0["verified"] = True
        ts0["stars_observed_at"] = ts

    for c in plan.get("capabilities", []):
        match = _match_capability_to_skill(c.get("name", ""), skills)
        if match:
            steps_new = [
                f"整目录拷贝：{match['dir_path']}/（{match['file_count']} 个文件"
                + ("，多文件 skill" if match["multi_file"] else "")
                + "）",
                f"目标路径：.claude/skills/{match['name']}/",
                f"SKILL.md 正文：{match.get('raw_url', '')}",
            ]
            corrections.append(
                f"capability {c.get('name', '')!r}: install_steps 人话→机器"
                f"（{match['dir_path']}, {match['file_count']} 文件）"
            )
            c["install_steps"] = steps_new
            c["verified_skill"] = {
                "name": match["name"],
                "dir_path": match["dir_path"],
                "multi_file": match["multi_file"],
                "file_count": match["file_count"],
            }

    # 用一手数据回填草稿的"待核实"问题。规则按关键词命中（容错问法差异，比单子串稳）；
    # 仅当一手数据确实支撑才标注：点名 skill 须真在树里，否则不乱认。未命中原样保留。
    # 答案全部从一手数据现取（星数/总数/文件数/目录），不写死本源 specifics（刻舟求剑 §5.3）。
    skill_by_norm = {_norm(s["name"]): s for s in skills}
    rules: list[tuple[list[str], str]] = [
        (
            ["颗星", "星数", "stars", "多少星", "stars为"],
            f"✅已核实：⭐{stars}（{ts} 取数，星数动态非定值）；画面/字幕所示星数为草稿 OCR，以一手为准",
        ),
        (
            ["个skill", "几个skill", "多少个", "skill总数", "个能力"],
            f"✅已核实：全仓 {len(skills)} 个 SKILL.md（见 install_list.json）；视频口述数字若与一手不符，以一手树为准",
        ),
    ]
    gm = skill_by_norm.get("grillme")
    if gm:
        rules.append(
            (
                ["完整提示词", "三句话", "四十二个词"],
                f"✅已核实：grill-me 在一手树中（{gm['file_count']} 文件"
                + ("，多文件 skill" if gm["multi_file"] else "")
                + f"，{gm['dir_path']}），整目录拷，详见 install_list.json",
            )
        )
    tdd = skill_by_norm.get("tdd")
    if tdd:
        rules.append(
            (
                ["具体文件名", "安装方式", "目录结构"],
                f"✅已核实：{tdd['dir_path']}，{tdd['file_count']} 文件"
                + ("，多文件 skill" if tdd["multi_file"] else "")
                + "，整目录拷",
            )
        )
    rules.append(
        (
            ["Claude Code", "特定工具", "仅适用"],
            "✅已核实：Claude Code 是 Anthropic 的 CLI（命令行工具）；SKILL.md+YAML frontmatter 即其 skill 格式",
        )
    )
    new_oq: list[str] = []
    resolved_n = 0
    for q in plan.get("open_questions", []):
        ql = q.lower()
        ans = next((a for kws, a in rules if any(kw.lower() in ql for kw in kws)), None)
        if ans:
            new_oq.append(ans)
            resolved_n += 1
        else:
            new_oq.append(q)
    plan["open_questions"] = new_oq
    # 诚实计数：实际命中几条就报几条，不空报"全部已解决"
    corrections.append(f"open_questions: {resolved_n}/{len(new_oq)} 条用一手数据回填标注")

    plan["_verify"] = {
        "verified_at": ts,
        "verified_repo": full,
        "stars": stars,
        "stars_observed_at": ts,
        "default_branch": info["default_branch"],
        "how_resolved": info["how_resolved"],
        "skill_total": len(skills),
        "install_list": str(install_list_path),
        "corrections": corrections,
        "note": "本块由 verify 模块一手核实后回填；草稿原始值见上方各字段（已就地纠正）。",
    }
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return corrections


def verify(source_dir: Path, *, repo_override: str | None = None, on_progress=None) -> dict:
    """对一个源目录跑溯源：读 plan.json → 按 form 分流 → 产 install_list.json + 回填 plan.json。

    章程 D2：产物形态由计划内容决定，不预设。入口读 plan.capabilities 的 form 分流：
      - 任一 MCP → _verify_mcp（多仓：遍历 capabilities 查 mcp_catalog，不走 resolve_repo）
      - 任一 config/code/repo → _verify_repo（clone&use：聚合到 github 仓，一仓一 item，clone 装跑）
      - 全 Skill → _verify_skill（单仓 resolve_repo + group_skill_dirs + 整目录拷，原逻辑不变）
    三路都产 install_list.json（含规范键 items[] + 兼容别名 skills[]）并回填 plan._verify。
    verify 纯 GitHub curl / 本地查表，不调 LLM、不耗 DeepSeek/Agnes 配额、不要 key。
    """
    source_dir = Path(source_dir)
    plan_path = source_dir / "plan.json"
    if not plan_path.exists():
        raise RuntimeError(f"没有 plan.json，先跑 plan：{plan_path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    caps = plan.get("capabilities", []) or []
    has_mcp = any((c.get("form") or "").upper() == "MCP" for c in caps)
    has_repo = any((c.get("form") or "").strip().lower() in _REPO_FORMS for c in caps)
    if has_mcp:
        return _verify_mcp(source_dir, plan_path, plan)
    if has_repo:
        return _verify_repo(source_dir, plan_path, plan)
    return _verify_skill(
        source_dir, plan_path, plan, repo_override=repo_override, on_progress=on_progress
    )


def _verify_skill(
    source_dir: Path,
    plan_path: Path,
    plan: dict,
    *,
    repo_override: str | None = None,
    on_progress=None,
) -> dict:
    """Skill 形态溯源：找真身 repo → 列 skill → 取 frontmatter → 产 install_list.json + 回填 plan。

    单仓架构：整条视频只对应一个 GitHub 仓，install 时整目录拷到 ~/.claude/skills/<name>/。
    原 verify() 逻辑原样搬入，仅补 items[] 兼容别名（同引用）+ form/item_total 供下游统一读。
    """
    draft_repos = parse_github_urls(json.dumps(plan, ensure_ascii=False))
    if repo_override:
        o, _, r = repo_override.partition("/")
        draft_repos = [(o, r)]
    draft_skill_names = [_cap_skill_name(c.get("name", "")) for c in plan.get("capabilities", [])]

    info, how = resolve_repo(draft_repos, draft_skill_names, plan=plan)
    owner, repo, branch = info["owner"], info["repo"], info["default_branch"]
    info["stars_observed_at"] = _now_iso()
    info["how_resolved"] = how

    tree = list_tree(owner, repo, branch)
    skills = group_skill_dirs(tree)
    enrich_with_frontmatter(owner, repo, branch, skills, on_progress=on_progress)
    for s in skills:
        for f in s["files"]:
            f["raw_url"] = raw_url(owner, repo, branch, f["path"])

    install_list_path = source_dir / "install_list.json"
    install_list = {
        "source_video": source_dir.name,
        "verified_repo": {
            "owner": owner,
            "repo": repo,
            "full_name": info["full_name"],
            "html_url": info["html_url"],
            "default_branch": branch,
            "stars": info["stars"],
            "stars_observed_at": info["stars_observed_at"],
            "description": info["description"],
            "how_resolved": how,
        },
        "branch": branch,
        "raw_base": f"{RAW_BASE}/{owner}/{repo}/{branch}",
        "install_method": "per_file_raw_download",
        "form": "Skill",
        "note": "每个 skill = files[] 列出的文件；install 时从 raw_url 逐文件下载到 .claude/skills/<name>/（不整目录拷）",
        "total": len(skills),
        "items": skills,  # 规范键（章程 D2，下游统一读 items[]）
        "skills": skills,  # 兼容别名，与 items 同数组引用
        "generated_at": _now_iso(),
    }
    install_list_path.write_text(
        json.dumps(install_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    corrections = backfill_plan(plan_path, plan, info, skills, install_list_path)
    return {
        "source_video": source_dir.name,
        "form": "Skill",
        "verified_repo": info["full_name"],
        "stars": info["stars"],
        "stars_observed_at": info["stars_observed_at"],
        "how_resolved": how,
        "skill_total": len(skills),
        "item_total": len(skills),
        "install_list": str(install_list_path),
        "corrections": corrections,
    }


def _verify_mcp(source_dir: Path, plan_path: Path, plan: dict) -> dict:
    """MCP 形态溯源（章程 D2）：遍历 plan.capabilities 查 mcp_catalog 建 install items。

    不走单仓 resolve_repo——MCP 视频常含多个不同仓（playwright/​filesystem/​…​），
    单仓解析会错配只取 traced_sources[0]。改为逐条 source_ref 取名 → catalog 查表：
    命中建 item（含注册信息 + usability + 装完前必做），未命中进 unresolved 透明降级
    交用户定夺（D19 先判 / D22 反黑箱），绝不臆造包装。纯查表 + 一手星数探测。
    """
    items, unresolved = group_mcp_items(plan)
    _probe_stars_for_items(items)

    install_list_path = source_dir / "install_list.json"
    install_list = {
        "source_video": source_dir.name,
        "install_method": "mcp_register",
        "form": "MCP",
        "note": "MCP 形态：每个 item = 一个 MCP 服务器；install 时按 mcp 注册到 ~/.claude.json"
        "（claude mcp add -s user [-- <command> <args...>]），不改 ~/.claude/skills/",
        "items": items,
        "skills": items,  # 兼容别名，与 items 同数组引用（旧下游读 skills[] 仍可用）
        "unresolved": unresolved,
        "total": len(items),
        "generated_at": _now_iso(),
    }
    install_list_path.write_text(
        json.dumps(install_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    corrections = backfill_plan_mcp(plan_path, plan, items, unresolved, install_list_path)
    return {
        "source_video": source_dir.name,
        "form": "MCP",
        "item_total": len(items),
        "unresolved_count": len(unresolved),
        "install_list": str(install_list_path),
        "corrections": corrections,
    }


# ===================== repo（clone&use）形态 =====================
# 章程 D2：form=config/code/repo 的能力——其真身是一个要 git clone 下来本地跑的开源项目
# （如 MoneyPrinterTurbo：文案/视频/音频字幕三能力同一仓），不是 SKILL.md 集合、也不是
# MCP 服务器。clone 一次即得全部能力，故按 github 仓去重聚合：一个仓 = 一个 item
# （form=repo, install_method=clone）。install 时 git clone + 装依赖 + 配置 + 运行
# （install._install_repo，章程 D20 install_method 非硬编码）。
# 与 MCP 的区别：MCP 每条 capability 对应一个独立 MCP 服务器；repo 形态多条 capability
# 常共用一个仓，按 full_name 聚合，capability 名收进 item.capabilities[]。

# form 取值（小写）表示「clone&use」形态：config（按说明并入配置）/ code（引入运行的代码）/ repo
_REPO_FORMS = ("config", "code", "repo")


def _ts_repo(ts: dict) -> tuple[str, str] | None:
    """从一条 traced_source 抠 github owner/repo。先匹配 url 字段里的 github.com/…，再退回
    name 字段的 owner/repo 写法。抠不到返回 None（交 unresolved，不臆造）。"""
    urls = parse_github_urls(json.dumps(ts, ensure_ascii=False))
    if urls:
        return urls[0]
    nm = (ts.get("name") or "").strip()
    m = re.match(r"^([A-Za-z0-9](?:[A-Za-z0-9-]*))/([A-Za-z0-9._-]+)$", nm)
    if m:
        return m.group(1), re.sub(r"\.git$", "", m.group(2))
    return None


def _repo_usability(steps: list[str]) -> tuple[str, list[str]]:
    """从 plan 的 install_steps 文本推 repo 项的 usability + 装完前必做（D22 反黑箱）。

    关键词命中式启发（非 LLM 臆造）：install_steps 是 plan 阶段据字幕归纳的「克隆+装依赖+
    配置+运行」步骤，含真实依赖线索。多命中按 needs_credentials > needs_runtime >
    needs_config > ready 取最高（要 key 的也常要配置，取最严）。返回 (usability, steps)。
    """
    blob = " ".join(steps).lower()
    post: list[str] = []
    if any(
        k in blob
        for k in (
            "api key",
            "api_key",
            "api-key",
            "密钥",
            "token",
            "openai",
            "deepseek",
            "llm api",
            "大模型api",
            "大模型 api",
            "api 密钥",
        )
    ):
        post.append("需配置大模型 API key（如 OPENAI_API_KEY / DEEPSEEK_API_KEY），缺则装了不能跑")
        return "needs_credentials", post
    if any(k in blob for k in ("ffmpeg", "imagemagick", "cuda", "gpu", "torch")):
        post.append("需装系统运行时（如 ffmpeg / GPU 驱动）才能跑")
        return "needs_runtime", post
    if any(
        k in blob
        for k in (".env", "config.toml", "config.yaml", "config.json", "配置文件", "修改配置")
    ):
        post.append("需按其 README 改配置文件（如 .env / config.toml）后才能跑")
        return "needs_config", post
    post.append("按其 README 克隆 + 装依赖 + 运行")
    return "ready", post


def _repo_credential_env(steps: list[str]) -> list[str] | None:
    """从 install_steps 文本推需填的凭证环境变量名（D22）。关键词命中，不臆造。"""
    blob = " ".join(steps).lower()
    envs: list[str] = []
    if any(k in blob for k in ("openai", "gpt")):
        envs.append("OPENAI_API_KEY")
    if "deepseek" in blob:
        envs.append("DEEPSEEK_API_KEY")
    if "moonshot" in blob or "kimi" in blob:
        envs.append("MOONSHOT_API_KEY")
    if "qwen" in blob or "通义" in blob or "dashscope" in blob:
        envs.append("DASHSCOPE_API_KEY")
    return envs or None


def group_repo_items(plan: dict) -> tuple[list[dict], list[dict]]:
    """repo（clone&use）形态：遍历 plan.capabilities，form ∈ {config,code,repo} 的按其
    traced_source 指向的 github 仓去重聚合成 item（一个仓一个 item）。一手 probe_repo 核实
    仓库存在 + 星数 + 默认分支，404 进 unresolved。从 plan install_steps 推 usability。
    返回 (items, unresolved)。纯 GitHub curl + 本地聚合，不调 LLM、不耗配额（章程 D18）。
    """
    traced = plan.get("traced_sources", []) or []
    caps = plan.get("capabilities", []) or []
    by_repo: dict[tuple[str, str], dict] = {}
    unresolved: list[dict] = []
    for cap in caps:
        f = (cap.get("form") or "").strip().lower()
        if f not in _REPO_FORMS:
            continue
        source_ref = cap.get("source_ref")
        ts: dict = {}
        if source_ref is not None:
            try:
                idx = int(source_ref) - 1
            except (TypeError, ValueError):
                idx = -1
            if 0 <= idx < len(traced):
                ts = traced[idx] or {}
        pair = _ts_repo(ts)
        if pair is None:
            unresolved.append(
                {
                    "name": cap.get("name", ""),
                    "reason": "repo 形态但 traced_sources 未含 github 仓库 URL，需人工核实",
                    "source_ref": source_ref,
                }
            )
            continue
        owner, repo = pair
        key = (owner.lower(), repo.lower())
        e = by_repo.setdefault(
            key,
            {
                "owner": owner,
                "repo": repo,
                "full_name": f"{owner}/{repo}",
                "capabilities": [],
                "steps": [],
            },
        )
        e["capabilities"].append(
            {
                "name": cap.get("name", ""),
                "form": f,
                "source_ref": source_ref,
                "install_steps": cap.get("install_steps", []) or [],
            }
        )
        e["steps"].extend(cap.get("install_steps", []) or [])

    items: list[dict] = []
    for e in by_repo.values():
        info = probe_repo(e["owner"], e["repo"])  # 一手核实存在 + 星数 + 默认分支
        if info is None:
            unresolved.append(
                {
                    "name": e["full_name"],
                    "reason": f"github 仓库 {e['full_name']} 404（不存在或私有），无法 clone",
                    "source_ref": None,
                }
            )
            continue
        usability, post = _repo_usability(e["steps"])
        items.append(
            {
                "name": info["repo"],
                "form": "repo",
                "install_method": "clone",
                "repo": info["full_name"],
                "owner": info["owner"],
                "url": info["html_url"],
                "default_branch": info["default_branch"],
                "stars": info["stars"],
                "stars_observed_at": _now_iso(),
                "description": info.get("description"),
                "usability": usability,
                "credential_env": _repo_credential_env(e["steps"]),
                "post_install_steps": post,
                "capabilities": e["capabilities"],
                "invoke_hint": (
                    f"git clone {info['html_url']} 后按 README 装依赖+配置+运行；"
                    f"提供 {len(e['capabilities'])} 项能力"
                ),
            }
        )
    return items, unresolved


def backfill_plan_repo(
    plan_path: Path,
    plan: dict,
    items: list[dict],
    unresolved: list[dict],
    install_list_path: Path,
) -> list[str]:
    """repo 形态回填 plan.json 的 _verify 块：记录待 clone 仓库、unresolved、install_list 路径。
    与 Skill/MCP 路径的 backfill 对应。返回 corrections 留痕。"""
    corrections: list[str] = []
    plan["_verify"] = {
        "verified_at": _now_iso(),
        "form": "repo",
        "verified_repos": [
            {"name": it["name"], "repo": it["repo"], "stars": it["stars"]} for it in items
        ],
        "unresolved": [
            {"name": u["name"], "reason": u["reason"], "source_ref": u.get("source_ref")}
            for u in unresolved
        ],
        "item_total": len(items),
        "install_list": str(install_list_path),
        "corrections": [],  # 先占位再回填，保证字段存在
        "note": "repo 形态：clone&use，整仓 clone + 装依赖 + 配置 + 运行（章程 D2/D20）。",
    }
    corrections.append(
        f"_verify: repo 形态回填（{len(items)} 仓库待 clone / {len(unresolved)} unresolved）"
    )
    plan["_verify"]["corrections"] = corrections
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return corrections


def _verify_repo(source_dir: Path, plan_path: Path, plan: dict) -> dict:
    """repo（clone&use）形态溯源（章程 D2）：聚合 form∈{config,code,repo} 的能力到其 github
    仓，一个仓 = 一个 item（form=repo, install_method=clone）。一手 probe_repo 核实仓库存在
    + 星数，从 plan install_steps 推 usability（needs_credentials/needs_runtime/needs_config/
    ready，D22 反黑箱）。产 install_list.json + 回填 plan._verify。纯 GitHub curl，不调 LLM。
    """
    items, unresolved = group_repo_items(plan)

    install_list_path = source_dir / "install_list.json"
    install_list = {
        "source_video": source_dir.name,
        "install_method": "clone",
        "form": "repo",
        "note": "repo 形态：每个 item = 一个要 git clone 下来本地跑的开源项目；"
        "install 时 clone 到本地 + 装依赖 + 配置 + 运行（不改 ~/.claude/skills/）",
        "items": items,
        "skills": items,  # 兼容别名，与 items 同数组引用
        "unresolved": unresolved,
        "total": len(items),
        "generated_at": _now_iso(),
    }
    install_list_path.write_text(
        json.dumps(install_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    corrections = backfill_plan_repo(plan_path, plan, items, unresolved, install_list_path)
    return {
        "source_video": source_dir.name,
        "form": "repo",
        "item_total": len(items),
        "unresolved_count": len(unresolved),
        "install_list": str(install_list_path),
        "corrections": corrections,
    }


# ---- 直接运行：python -m skillbrew.verify <源目录> ----
def _main() -> int:
    import sys

    if len(sys.argv) < 2:
        print("用法: python -m skillbrew.verify <源目录> [--repo owner/repo]")
        print("     源目录需含 plan.json（先跑 plan）")
        return 1
    src = Path(sys.argv[1])
    repo_override = None
    if "--repo" in sys.argv:
        repo_override = sys.argv[sys.argv.index("--repo") + 1]
    print(f"[溯源] {src}")
    s = verify(src, repo_override=repo_override)
    form = s.get("form", "Skill")
    if form == "MCP":
        print(
            f"[OK] MCP 形态核实：解析命中 {s['item_total']} 个 / unresolved {s['unresolved_count']} 个"
        )
        print(f"     install_list → {s['install_list']}")
        print(f"     plan.json 纠正 {len(s['corrections'])} 处")
    elif form == "repo":
        print(
            f"[OK] repo 形态核实：待 clone 仓库 {s['item_total']} 个 / unresolved {s['unresolved_count']} 个"
        )
        print(f"     install_list → {s['install_list']}")
        print(f"     plan.json 纠正 {len(s['corrections'])} 处")
    else:
        print(f"[OK] 一手核实：{s['verified_repo']}（⭐{s['stars']}，{s['stars_observed_at']}）")
        print(f"     定位：{s['how_resolved']}")
        print(f"     全仓 skill {s['skill_total']} 个 → {s['install_list']}")
        print(f"     plan.json 纠正 {len(s['corrections'])} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
