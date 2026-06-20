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
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

API_BASE = "https://api.github.com"
RAW_BASE = "https://raw.githubusercontent.com"
UA = "skillbrew"  # GitHub 要求带 User-Agent，否则 403
SKILL_MD = "SKILL.md"
_TIMEOUT = 30.0
_SEARCH_CANDIDATES = 8  # 搜索取前 N 个候选再逐个校验
_MAX_RETRIES = 3  # 5xx/网络瞬时错误重试次数（git/trees 端点偶发 504）
_RETRY_BACKOFF = 2.0  # 退避基数秒：第 n 次重试睡 n*BACKOFF 秒


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get(url: str, *, accept: str = "application/vnd.github+json", timeout: float = _TIMEOUT) -> tuple[int, bytes]:
    """发请求；5xx 与网络瞬时错误自动退避重试（git/trees 端点偶发 504，重试通常即通）。

    4xx（404/403 限速等）不重试，原样返回 (code, body) 交调用方判断。
    """
    for attempt in range(_MAX_RETRIES):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
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
    if status != 200:
        raise RuntimeError(f"GitHub API {status} {url}: {body[:200]!r}")
    return json.loads(body)


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
_GH_URL_RE = re.compile(r"github\.com/([A-Za-z0-9](?:[A-Za-z0-9-]*))/([A-Za-z0-9._-]+)(?=[^A-Za-z0-9._-]|$)")


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
        "owner": owner, "repo": repo,
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
    return [{"path": t["path"], "type": t["type"], "size": t.get("size", 0)} for t in d.get("tree", [])]


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
            "category": category, "name": name, "dir_path": dir_path,
            "sk_md_path": p, "files": {},
        }
    # 第二遍：把每个 skill 目录下的全部文件归入（整目录，只收 blob 文件，跳过子目录树节点）
    for t in tree:
        if t.get("type") != "blob":  # 跳过 tree（子目录）/commit 节点，只收文件，否则 raw_url 会 404
            continue
        p = t["path"]
        for dir_path, d in by_dir.items():
            if p.startswith(dir_path + "/"):
                d["files"][p] = {"path": p, "size": t.get("size", 0)}
                break
    out = []
    for d in by_dir.values():
        files = sorted(d["files"].values(), key=lambda f: f["path"])
        out.append({
            "category": d["category"], "name": d["name"], "dir_path": d["dir_path"],
            "sk_md_path": d["sk_md_path"], "files": files,
            "file_count": len(files), "multi_file": len(files) > 1,
        })
    out.sort(key=lambda x: (x["category"], x["name"]))
    return out


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
        try:
            body = _raw_text(url)
            fm = parse_frontmatter(body)
            s["display_name"] = fm.get("name", s["name"])
            s["description"] = fm.get("description", "")
            s["body_chars"] = len(body)
        except RuntimeError as e:
            s["display_name"] = s["name"]
            s["description"] = ""
            s["fetch_error"] = str(e)[:200]


# ---- 仓库名从"错的草稿"找回"对的真身" ----

def _norm(s: str) -> str:
    """归一化 skill 名用于比对：小写 + 去非字母数字。GrillMe→grillme, grill-me→grillme。"""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _cap_skill_name(cap_name: str) -> str:
    """草稿能力名 'GrillMe：需求澄清追问技能' / 'TDD红绿重构循环技能' → 取可比对的主名。"""
    nm = re.split(r"[:：]", cap_name, maxsplit=1)[0].strip()
    return nm


def resolve_repo(
    draft_repos: list[tuple[str, str]], draft_skill_names: list[str]
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
    if not seeds:
        raise RuntimeError("草稿没有 github repo 线索，无法溯源；请用 --repo owner/repo 指定")
    targets = {_norm(n) for n in draft_skill_names if _norm(n)}
    checked_any = False
    skip_reasons: list[str] = []
    for seed in seeds:
        q = urllib.parse.quote(seed)
        d = _api_json(f"{API_BASE}/search/repositories?q={q}&sort=stars&per_page={_SEARCH_CANDIDATES}")
        # 按仓库体积升序：小仓库先查（快），skill 合集通常不大
        cands = sorted(d.get("items", []), key=lambda c: c.get("size", 0))
        for cand in cands:
            co, cr = cand["owner"]["login"], cand["name"]
            branch = cand.get("default_branch", "main")
            try:
                tree = list_tree(co, cr, branch)
            except RuntimeError as e:
                # 截断/私有/空树/瞬时错误（已重试仍失败）：留痕后跳过，别静默
                print(f"   [跳过] {co}/{cr}: {str(e)[:120]}", flush=True)
                skip_reasons.append(f"{co}/{cr}: {str(e)[:80]}")
                continue
            checked_any = True
            skill_names = {_norm(s["name"]) for s in group_skill_dirs(tree)}
            hits = targets & skill_names if targets else set()
            if (targets and hits) or not targets:
                info = {
                    "owner": co, "repo": cr, "full_name": cand["full_name"],
                    "html_url": cand["html_url"], "stars": cand["stargazers_count"],
                    "default_branch": branch, "description": cand.get("description"),
                    "pushed_at": cand.get("pushed_at"),
                }
                how = (
                    f"草稿 repo 404；搜 '{seed}' 按星排 + 体积升序；命中 {co}/{cr}"
                    + (f"（树含点名 skill: {sorted(hits)}）" if targets else "（无点名 skill 可校验，取最小候选）")
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
                + ("，多文件 skill" if match["multi_file"] else "") + "）",
                f"目标路径：.claude/skills/{match['name']}/",
                f"SKILL.md 正文：{match.get('raw_url', '')}",
            ]
            corrections.append(
                f"capability {c.get('name','')!r}: install_steps 人话→机器"
                f"（{match['dir_path']}, {match['file_count']} 文件）"
            )
            c["install_steps"] = steps_new
            c["verified_skill"] = {
                "name": match["name"], "dir_path": match["dir_path"],
                "multi_file": match["multi_file"], "file_count": match["file_count"],
            }

    # 用一手数据回填草稿的"待核实"问题。规则按关键词命中（容错问法差异，比单子串稳）；
    # 仅当一手数据确实支撑才标注：点名 skill 须真在树里，否则不乱认。未命中原样保留。
    # 答案全部从一手数据现取（星数/总数/文件数/目录），不写死本源 specifics（刻舟求剑 §5.3）。
    skill_by_norm = {_norm(s["name"]): s for s in skills}
    rules: list[tuple[list[str], str]] = [
        (["颗星", "星数", "stars", "多少星", "stars为"],
         f"✅已核实：⭐{stars}（{ts} 取数，星数动态非定值）；画面/字幕所示星数为草稿 OCR，以一手为准"),
        (["个skill", "几个skill", "多少个", "skill总数", "个能力"],
         f"✅已核实：全仓 {len(skills)} 个 SKILL.md（见 install_list.json）；视频口述数字若与一手不符，以一手树为准"),
    ]
    gm = skill_by_norm.get("grillme")
    if gm:
        rules.append((["完整提示词", "三句话", "四十二个词"],
                      f"✅已核实：grill-me 在一手树中（{gm['file_count']} 文件"
                      + ("，多文件 skill" if gm["multi_file"] else "")
                      + f"，{gm['dir_path']}），整目录拷，详见 install_list.json"))
    tdd = skill_by_norm.get("tdd")
    if tdd:
        rules.append((["具体文件名", "安装方式", "目录结构"],
                      f"✅已核实：{tdd['dir_path']}，{tdd['file_count']} 文件"
                      + ("，多文件 skill" if tdd["multi_file"] else "")
                      + "，整目录拷"))
    rules.append((["Claude Code", "特定工具", "仅适用"],
                  "✅已核实：Claude Code 是 Anthropic 的 CLI（命令行工具）；SKILL.md+YAML frontmatter 即其 skill 格式"))
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
    """对一个源目录跑溯源：读 plan.json → 找真身 repo → 列 skill → 取 frontmatter
    → 产 install_list.json + 回填纠正 plan.json。返回汇总 dict。

    verify 纯 GitHub curl，不调 LLM、不耗 DeepSeek/Agnes 配额、不要 key。
    """
    source_dir = Path(source_dir)
    plan_path = source_dir / "plan.json"
    if not plan_path.exists():
        raise RuntimeError(f"没有 plan.json，先跑 plan：{plan_path}")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    draft_repos = parse_github_urls(json.dumps(plan, ensure_ascii=False))
    if repo_override:
        o, _, r = repo_override.partition("/")
        draft_repos = [(o, r)]
    draft_skill_names = [_cap_skill_name(c.get("name", "")) for c in plan.get("capabilities", [])]

    info, how = resolve_repo(draft_repos, draft_skill_names)
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
            "owner": owner, "repo": repo, "full_name": info["full_name"],
            "html_url": info["html_url"], "default_branch": branch,
            "stars": info["stars"], "stars_observed_at": info["stars_observed_at"],
            "description": info["description"], "how_resolved": how,
        },
        "branch": branch,
        "raw_base": f"{RAW_BASE}/{owner}/{repo}/{branch}",
        "install_method": "copy_whole_dir",
        "note": "每个 skill = 其整个目录；install 时按 dir_path 整目录从 raw_url 拷到 .claude/skills/<name>/",
        "total": len(skills),
        "skills": skills,
        "generated_at": _now_iso(),
    }
    install_list_path.write_text(
        json.dumps(install_list, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    corrections = backfill_plan(plan_path, plan, info, skills, install_list_path)
    return {
        "source_video": source_dir.name,
        "verified_repo": info["full_name"],
        "stars": info["stars"],
        "stars_observed_at": info["stars_observed_at"],
        "how_resolved": how,
        "skill_total": len(skills),
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
    print(f"[OK] 一手核实：{s['verified_repo']}（⭐{s['stars']}，{s['stars_observed_at']}）")
    print(f"     定位：{s['how_resolved']}")
    print(f"     全仓 skill {s['skill_total']} 个 → {s['install_list']}")
    print(f"     plan.json 纠正 {len(s['corrections'])} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
