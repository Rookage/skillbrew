"""install：安装 —— 照 dedup 判定的 new 能力，按形态分发安装并登记台账。

形态分发（章程 D2/D20，产物形态由计划内容决定、不预设）：
  - form=="Skill" → 整目录从 GitHub raw 拷到本地 .claude/skills/<name>/（须 SKILL.md）
  - form=="MCP"   → 注册进 ~/.claude.json mcpServers（默认 user scope），CLI-first：
                    优先 `claude mcp add -s user ...`（官方原子操作），无 binary 时
                    fallback 原子 JSON 合并（.bak + mtime 守卫 + 写后 json.loads 校验 + 回滚）
  - form=="repo"  → git clone 到 ~/.claude/clones/<name>/ + 装依赖（阿里云镜像防 hang）+
                    登记台账；克隆即用，不改 ~/.claude/skills/。与 MCP 不同：repo 的
                    needs_credentials（如大模型 API key）**不跳过克隆+装依赖**——
                    克隆+装依赖即"安装"，key 只在"运行"时才用；usability 透明记进
                    台账/报告（dry-run 标「跑时需凭证」），不替用户造 key

刹车（章程 D18/刹车设计）：install 默认 dry-run——只列要装什么、不下载、不注册、不写台账；
带 --approve 才真落盘 + 写台账，保"你落盘就是什么"。

装哪些：
  - dedup 判 new 的 → 装（按 form 分发）
  - dedup 判 merge 的 → 不自动装（整并需人工确认，标出来留给后面）
  - dedup 判 skip 的 → 不装（已装/已整并）
  - new 里 category=deprecated 的 → 默认跳过（--include-deprecated 才装）
  - needs_credentials 的 MCP（如 github 需 PAT）→ dry-run 高亮「需凭证」，
    --approve 默认跳过真装（除非对应 credential_env 已在环境里配好），不替用户造凭证
  - needs_config 的 MCP（如 filesystem 的 <DIRS>）→ --approve 把 <DIRS> 默认填
    cwd+home 再注册（章程风险清单「默认填占位并高亮待改」）；仍解析不出的 <…> 占位 → 跳过

unresolved（verify 透明降级，如 memos 无官方 MCP）→ 不在 items、不在 to_install，
原样透传进报告标「待定夺」，install 不猜包装（D19/D22）。

install 是 dedup-driven（照 dedup 的 new 装），不读 recommend.json——recommend 是
判断步（值不值得装）出建议名单，install 只管"装哪些 new、按什么形态装"。挑着买
（D20）由你在 recommend 步看到 verdict 后自行定夺（manual/ai 模式可覆写）。

纯 GitHub raw 下载（raw 不耗 API 限额）+ 标准库 + claude CLI；不调 LLM、不耗配额。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config
from . import registry
from .verify import parse_frontmatter  # 复用 SKILL.md frontmatter 轻量解析

UA = "skillbrew"  # GitHub raw 也要求带 User-Agent
_TIMEOUT = 30.0
_MAX_RETRIES = 3  # 5xx/网络瞬时错误重试（raw 偶发 504，同 verify._get）
_RETRY_BACKOFF = 2.0


def _now_iso() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _fetch_bytes(url: str) -> bytes:
    """下载文件字节；5xx 与网络瞬时错误退避重试（策略同 verify._get）。"""
    for attempt in range(_MAX_RETRIES):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if 500 <= e.code < 600 and attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BACKOFF * (attempt + 1))
                continue  # 5xx 网关瞬时错误，退避后重试
            raise RuntimeError(f"下载失败 {e.code} {url}") from e
        except urllib.error.URLError as e:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_RETRY_BACKOFF * (attempt + 1))
                continue  # 网络抖动，重试
            raise RuntimeError(f"网络失败 {url}: {e}") from e
    raise RuntimeError(f"下载重试用尽 {url}")


def _rel_within(skill_dir_path: str, file_path: str) -> Path:
    """把仓库里的 file_path 转成 skill 目录内的相对路径，用于落地。

    skill_dir_path='skills/engineering/tdd'，file_path='skills/engineering/tdd/mocking.md'
    → Path('mocking.md')。防路径穿越：拒绝绝对路径与 .. 。
    """
    prefix = skill_dir_path.rstrip("/") + "/"
    rel = file_path[len(prefix):] if file_path.startswith(prefix) else Path(file_path).name
    p = Path(rel)
    if p.is_absolute() or any(part == ".." for part in p.parts):
        raise RuntimeError(f"可疑路径，拒绝写入：{file_path}")
    return p


# ==================== 形态分发：Skill 整目录拷 ====================

def _install_skill(conn, item: dict, decision: dict, target: Path,
                   source_video: str, full_name: str,
                   on_progress=None, i: int = 0, total: int = 1) -> dict:
    """Skill 形态：整目录从 GitHub raw 拷到 target/<name>/，登记台账。返回 installed 条目。

    逻辑与旧版一致（每个 skill = 其目录下全部文件，raw 下载，SKILL.md 抠 frontmatter），
    仅抽出成函数 + form 取 item 真实形态（修旧版硬编码 form="Skill"）。
    """
    name = decision["name"]
    if on_progress:
        on_progress(item, i, total)
    dest_dir = target / name
    dest_dir.mkdir(parents=True, exist_ok=True)
    n_files = 0
    display_name = name
    for f in item.get("files", []):
        rel = _rel_within(item["dir_path"], f["path"])
        dest_file = dest_dir / rel
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        data = _fetch_bytes(f["raw_url"])
        dest_file.write_bytes(data)
        n_files += 1
        if rel.name == "SKILL.md":  # 顺手抠 frontmatter 拿规范名
            try:
                fm = parse_frontmatter(data.decode("utf-8", errors="replace"))
                if fm.get("name"):
                    display_name = fm["name"]
            except Exception:  # noqa: BLE001  frontmatter 解析失败不阻塞
                pass
    registry.upsert_skill(
        conn, name,
        display_name=display_name,
        category=item.get("category", decision.get("category", "")),
        form=item.get("form", "Skill"),
        source=full_name,
        source_video=source_video,
        install_path=str(dest_dir),
        file_count=n_files,
        status="active",
        attribution=f"{full_name}（GitHub 开源）",
        dedup_note="dedup 判定 new，整目录拷贝安装",
        installed_at=_now_iso(),
    )
    return {"name": name, "display_name": display_name,
            "form": "Skill", "file_count": n_files, "path": str(dest_dir)}


# ==================== 形态分发：MCP 注册 ====================

def _credentials_configured(item: dict) -> bool:
    """needs_credentials 的 MCP 是否已在环境里配好凭证（不替用户造凭证）。

    credential_env 形如 ["GITHUB_PERSONAL_ACCESS_TOKEN"]；全在 os.environ 里才算配好。
    无 credential_env 或非 needs_credentials → 视为无需凭证（True，可装）。
    """
    cred = item.get("credential_env") or []
    if not cred:
        return True
    return all(os.environ.get(k) for k in cred)


def _resolve_args(mcp: dict) -> tuple[list[str], bool]:
    """解析 args 里的 <DIRS> 占位符（needs_config），默认填 cwd+home。

    返回 (resolved_args, substituted_dirs)。其它 <…> 占位符不在本函数替换
    （由调用方 _has_unresolved_placeholder 兜底判跳过，避免注册坏服务器）。
    """
    args = [str(a) for a in (mcp.get("args") or [])]
    default_dirs = [str(Path.cwd()), str(Path.home())]
    sub = False
    out: list[str] = []
    for a in args:
        if a.strip().lower() == "<dirs>":
            # 整个 arg 就是 <DIRS> → 展开成多个独立目录参数
            # （filesystem server 要求每个允许目录各占一个 argv，连成带空格的单串会注册成坏服务器）
            out.extend(default_dirs)
            sub = True
        elif "<dirs>" in a.lower():
            # <DIRS> 仅作为子串嵌在更大字符串里 → 退化为空格连接替换
            a = a.replace("<DIRS>", " ".join(default_dirs)).replace("<dirs>", " ".join(default_dirs))
            sub = True
            out.append(a)
        else:
            out.append(a)
    return out, sub


def _has_unresolved_placeholder(resolved_args: list[str]) -> bool:
    """<DIRS> 已替换后，args 里若仍含 <…> 占位 → 不能装（needs_config 未解析），跳过。"""
    return any("<" in a and ">" in a for a in resolved_args)


def _inject_env(item: dict) -> dict:
    """收集 credential_env / env_template 里 os.environ 真有的键值（空占位不注入）。"""
    keys = list(item.get("credential_env") or []) + list((item.get("env_template") or {}).keys())
    return {k: os.environ[k] for k in keys if os.environ.get(k)}


def _mcp_server_config(item: dict, resolved_args: list[str]) -> dict:
    """构造要注册的 MCP server 配置（与 ~/.claude.json mcpServers 条目同构）。

    stdio：{command, args, env(仅注入已配置凭证)}；http/sse：{type, url, headers}。
    """
    mcp = item.get("mcp") or {}
    transport = (mcp.get("transport") or "stdio").lower()
    if transport in ("http", "sse"):
        server = {"type": transport, "url": mcp.get("url", "")}
        if mcp.get("headers"):
            server["headers"] = mcp["headers"]
        return server
    server = {"command": mcp.get("command", "")}
    if resolved_args:
        server["args"] = list(resolved_args)
    env_inj = _inject_env(item)
    if env_inj:
        server["env"] = env_inj
    return server


def _install_mcp_cli(bin_path: str, name: str, item: dict,
                     scope: str, transport: str, resolved_args: list[str]) -> dict:
    """CLI-first：`claude mcp add` 注册。stdio 用 `--` 分隔 command/args，http/sse 用 -t。

    校验 returncode，再 `claude mcp get <name>` 确认注册成功。返回 registered_via/install_path。
    注：`claude mcp add` 默认 scope=local，必须显式 -s <scope>（本环境 mcp_default_scope=user）。
    """
    mcp = item.get("mcp") or {}
    cmd = [bin_path, "mcp", "add"]
    if transport in ("http", "sse"):
        cmd += ["-s", scope, "-t", transport, name, mcp.get("url", "")]
        for h in mcp.get("headers") or []:
            cmd += ["-H", h]
    else:  # stdio：name 在前，-e 注入已配凭证，-- 后接 command + args
        cmd += [name, "-s", scope]
        for k, v in _inject_env(item).items():
            cmd += ["-e", f"{k}={v}"]
        cmd.append("--")
        if mcp.get("command"):
            cmd.append(mcp["command"])
        cmd += list(resolved_args)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=_TIMEOUT * 2)
    if proc.returncode != 0:
        raise RuntimeError(f"claude mcp add 失败 {name}: {(proc.stderr or proc.stdout).strip()}")
    # 确认：claude mcp get <name> 能取到（returncode 0 或名字出现在输出里都算成功）
    getp = subprocess.run([bin_path, "mcp", "get", name],
                          capture_output=True, text=True, timeout=_TIMEOUT)
    if getp.returncode != 0 and name not in (getp.stdout + getp.stderr):
        raise RuntimeError(f"claude mcp add 后 get 不到 {name}: {(getp.stderr or getp.stdout).strip()}")
    return {"registered_via": "cli",
            "install_path": f"~/.claude.json:mcpServers/{name} (scope={scope})"}


def _install_mcp_json_merge(name: str, item: dict, scope: str,
                            transport: str, resolved_args: list[str]) -> dict:
    """无 claude binary 时 fallback：原子合并进 ~/.claude.json（user/local）或 ./.mcp.json（project）。

    读 → 备份 .bak → mtime 守卫（读后写前对比，被改则重读重放本条）→ 合并 →
    写后 json.loads 校验可解析 → 失败回滚 .bak。user scope 写顶层 mcpServers。
    """
    from . import config
    server = _mcp_server_config(item, resolved_args)

    if scope == "project":  # project scope 写独立文件 ./.mcp.json
        pm = Path.cwd() / ".mcp.json"
        pdata: dict = {}
        if pm.exists():
            try:
                pdata = json.loads(pm.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001  损坏从空重建，.bak 不适用于独立文件
                pdata = {}
        pdata.setdefault("mcpServers", {})[name] = server
        pm.write_text(json.dumps(pdata, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"registered_via": "json-merge",
                "install_path": f"{pm}:mcpServers/{name} (scope=project)"}

    cj = config.claude_json_path
    bak = cj.with_suffix(cj.suffix + ".bak")

    def _read() -> dict:
        if not cj.exists():
            return {}
        try:
            return json.loads(cj.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001  ~/.claude.json 损坏：从空重建（.bak 兜底保其它配置）
            return {}

    data = _read()
    mtime0 = cj.stat().st_mtime if cj.exists() else None
    if cj.exists():
        bak.write_bytes(cj.read_bytes())  # 备份

    if scope == "user":
        data.setdefault("mcpServers", {})[name] = server
    elif scope == "local":
        cwd = str(Path.cwd())
        data.setdefault("projects", {}).setdefault(cwd, {}).setdefault("mcpServers", {})[name] = server
    else:
        raise RuntimeError(f"未知 MCP scope: {scope}")

    # mtime 守卫：写前再 stat，被外部改过则重读重放本条（防覆盖并发改动）
    if cj.exists() and cj.stat().st_mtime != mtime0:
        fresh = _read()
        if scope == "user":
            fresh.setdefault("mcpServers", {})[name] = server
        else:  # local
            fresh.setdefault("projects", {}).setdefault(str(Path.cwd()), {}).setdefault("mcpServers", {})[name] = server
        data = fresh

    cj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:  # 写后校验可解析；失败回滚 .bak
        json.loads(cj.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        if bak.exists():
            cj.write_bytes(bak.read_bytes())
        raise RuntimeError(f"~/.claude.json 写后校验失败，已回滚 .bak：{name}")
    return {"registered_via": "json-merge",
            "install_path": f"~/.claude.json:mcpServers/{name} (scope={scope})"}


def _install_mcp(conn, item: dict, decision: dict,
                 source_video: str, full_name: str,
                 resolved_args: list[str], substituted_dirs: bool,
                 on_progress=None, i: int = 0, total: int = 1) -> dict:
    """注册一个 MCP 服务器 + 登记台账。CLI-first，无 binary 走原子 JSON 合并。

    返回 installed 条目 {name, form, scope, transport, registered_via, usability, path, dirs_filled}。
    """
    from . import config
    name = decision["name"]
    if on_progress:
        on_progress(item, i, total)
    mcp = item.get("mcp") or {}
    scope = mcp.get("scope") or config.mcp_default_scope
    transport = (mcp.get("transport") or "stdio").lower()

    bin_path = config.claude_bin()
    if bin_path:
        via = _install_mcp_cli(bin_path, name, item, scope, transport, resolved_args)
    else:
        via = _install_mcp_json_merge(name, item, scope, transport, resolved_args)

    usability = item.get("usability", "ready")
    dedup_note = f"dedup 判定 new，{via['registered_via']} 注册（scope={scope}）"
    if substituted_dirs:
        dedup_note += "；<DIRS> 已默认填 cwd+home，建议按需收窄"
    registry.upsert_skill(
        conn, name,
        display_name=item.get("capability_name") or name,
        category="",
        form="MCP",
        source=item.get("repo") or full_name,
        source_video=source_video,
        install_path=via["install_path"],
        file_count=0,
        status="active",
        attribution=f"{item.get('repo') or full_name}（MCP 服务器）",
        dedup_note=dedup_note,
        installed_at=_now_iso(),
    )
    return {"name": name, "form": "MCP", "scope": scope, "transport": transport,
            "registered_via": via["registered_via"], "usability": usability,
            "dirs_filled": substituted_dirs, "path": via["install_path"]}


# ==================== 形态分发：repo 克隆即用 ====================

# 阿里云 PyPI（Python 包索引）镜像：云电脑直连 pypi 慢、易 hang 死，统一走镜像
_PIP_MIRROR_ARGS = [
    "-i", "https://mirrors.aliyun.com/pypi/simple/",
    "--trusted-host", "mirrors.aliyun.com",
]

# 装依赖给宽裕超时：重依赖（torch/moviepy/faster-whisper 等）装包远慢于网络探测，
# _TIMEOUT（30s）系给 GitHub API 之类快探用的；这里放大并 catch 超时降级，不崩 install。
_DEPS_INSTALL_TIMEOUT = _TIMEOUT * 40  # 1200s ≈ 20min，阿里云镜像下够装一坨重依赖


def _detect_deps_method(clone_dir: Path) -> str:
    """探测克隆目录里的依赖清单类型，决定装依赖走哪条路。

    pip 系（requirements.txt / pyproject.toml）走 ``python -m pip``；npm 系（package.json）
    走 ``npm install``；都没有返回 none（克隆已成功，依赖可后补）。
    """
    if (clone_dir / "requirements.txt").exists():
        return "pip-requirements"
    if (clone_dir / "pyproject.toml").exists():
        return "pip-pyproject"
    if (clone_dir / "package.json").exists():
        return "npm"
    return "none"


def _install_repo_deps(clone_dir: Path, method: str) -> dict:
    """按探测到的依赖清单装依赖（阿里云镜像防 hang）。返回 {installed, detail}。

    装依赖失败**不抛**——克隆已成功，依赖可后补；超时也**不抛**：catch
    ``TimeoutExpired`` 降级为 ``installed=False``（重依赖如 torch/moviepy 装包慢，
    给宽裕 ``_DEPS_INSTALL_TIMEOUT``，仍超时则留待后补）。detail 透传 stderr 头供诊断。
    """
    if method == "none":
        return {"installed": False, "detail": "未发现依赖清单，跳过装依赖"}
    if method == "npm":
        npm = shutil.which("npm")
        if not npm:
            return {"installed": False, "detail": "发现 package.json 但本机无 npm，跳过（可后补）"}
        cmd, label = [npm, "install"], "npm install"
    else:
        # pip 系：requirements.txt 直接 -r；pyproject.toml 装当前包
        pip_cmd = [sys.executable, "-m", "pip", "install"]
        if method == "pip-requirements":
            pip_cmd += ["-r", "requirements.txt"] + _PIP_MIRROR_ARGS
        else:  # pip-pyproject
            pip_cmd += ["."] + _PIP_MIRROR_ARGS
        cmd, label = pip_cmd, "pip install"
    try:
        proc = subprocess.run(cmd, cwd=clone_dir, capture_output=True,
                              text=True, timeout=_DEPS_INSTALL_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {"installed": False,
                "detail": f"{label} 超时（{_DEPS_INSTALL_TIMEOUT:.0f}s），克隆已成功、依赖可后补"}
    ok = proc.returncode == 0
    return {"installed": ok,
            "detail": f"{label} {'成功' if ok else '失败'}: {(proc.stderr or proc.stdout).strip()[:200]}"}


def _install_repo(conn, item: dict, decision: dict,
                  source_video: str, full_name: str,
                  on_progress=None, i: int = 0, total: int = 1) -> dict:
    """repo 形态：git clone 到 config.repo_clones_dir()/<name>/ + 装依赖 + 登记台账。

    克隆即用（不改 ~/.claude/skills/）：克隆 + 装依赖即「安装」；运行所需的大模型 API key
    属 needs_credentials，但**不跳过克隆**（key 只在跑的时候才用，装的时候不需要），
    usability 透明记进台账/报告。已克隆过的目录幂等跳过 git clone（不覆盖本地改动）。
    返回 installed 条目 {name, form, repo, install_method, usability, path, branch,
    deps_method, deps_installed, cloned_now}。
    """
    name = decision["name"]
    if on_progress:
        on_progress(item, i, total)
    repo_full = item.get("repo") or full_name  # 如 harry0703/MoneyPrinterTurbo
    url = item.get("url") or f"https://github.com/{repo_full}"
    branch = item.get("default_branch") or "main"
    clones_root = config.repo_clones_dir()
    clones_root.mkdir(parents=True, exist_ok=True)
    clone_dir = clones_root / name

    cloned_now = False
    if clone_dir.exists() and (clone_dir / ".git").exists():
        clone_detail = "已存在，跳过 git clone（幂等）"  # 不覆盖用户可能的本地改动
    else:
        git_bin = shutil.which("git")
        if not git_bin:
            raise RuntimeError(f"本机无 git，无法克隆 {repo_full}（先装 git 再重跑）")
        # --depth 1 浅克隆更快；先按记录的默认分支克隆，失败则退回 git 默认分支（防分支名漂移）
        proc = subprocess.run(
            [git_bin, "clone", "--depth", "1", "--branch", branch, url, str(clone_dir)],
            capture_output=True, text=True, timeout=_TIMEOUT * 10,
        )
        if proc.returncode != 0:
            if clone_dir.exists():
                shutil.rmtree(clone_dir, ignore_errors=True)
            proc = subprocess.run(
                [git_bin, "clone", "--depth", "1", url, str(clone_dir)],
                capture_output=True, text=True, timeout=_TIMEOUT * 10,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"git clone 失败 {repo_full}: {(proc.stderr or proc.stdout).strip()}")
            clone_detail = f"git clone --depth 1 成功（记录分支 {branch} 不匹配，退回默认分支）"
        else:
            clone_detail = f"git clone --depth 1 --branch {branch} 成功"
        cloned_now = True

    deps_method = _detect_deps_method(clone_dir)
    deps = _install_repo_deps(clone_dir, deps_method)  # 阿里云镜像防 hang

    usability = item.get("usability", "ready")
    dedup_note = f"dedup 判定 new，{clone_detail}；{deps['detail']}"
    registry.upsert_skill(
        conn, name,
        display_name=name,
        category="",
        form="repo",
        source=repo_full,
        source_video=source_video,
        install_path=str(clone_dir),
        file_count=0,
        status="active",
        attribution=f"{repo_full}（GitHub 开源，克隆即用）",
        dedup_note=dedup_note,
        installed_at=_now_iso(),
    )
    return {"name": name, "form": "repo", "repo": repo_full, "install_method": "clone",
            "usability": usability, "path": str(clone_dir), "branch": branch,
            "deps_method": deps_method, "deps_installed": deps["installed"],
            "cloned_now": cloned_now}


# ==================== 主流程 ====================

def install(
    source_dir: Path, *, target_dir: Path | str | None = None,
    db_path: Path | str | None = None, approve: bool = False,
    include_deprecated: bool = False, on_progress=None,
) -> dict:
    """对一个源目录跑安装：读 install_list.json + dedup.json → 挑 new 按形态分发 → 登记台账。

    approve=False（默认）= dry-run，只返回计划（to_install/items_detail/skipped_*/unresolved），
    不下载、不注册、不写台账。approve=True = 真装（Skill 整目录拷 / MCP 注册）+ upsert 台账 + 记会话。
    返回报告 dict。纯 GitHub raw + 标准库 + claude CLI，不调 LLM。
    target_dir 仅对 Skill 形态有意义（默认 ~/.claude/skills）；MCP 注册到 ~/.claude.json。
    """
    source_dir = Path(source_dir)
    il_path = source_dir / "install_list.json"
    dd_path = source_dir / "dedup.json"
    if not il_path.exists():
        raise RuntimeError(f"没有 install_list.json，先跑 verify：{il_path}")
    if not dd_path.exists():
        raise RuntimeError(f"没有 dedup.json，先跑 dedup：{dd_path}")
    install_list = json.loads(il_path.read_text(encoding="utf-8"))
    dedup_report = json.loads(dd_path.read_text(encoding="utf-8"))

    repo = install_list.get("verified_repo", {})
    full_name = repo.get("full_name", "")
    source_video = install_list.get("source_video", source_dir.name)

    # items 为规范键，skills 为兼容别名（同数组引用）；旧 artifact 只有 skills
    items = install_list.get("items") or install_list.get("skills", [])
    by_name = {s["name"]: s for s in items if s.get("name")}  # 回查 files/raw_url/dir_path/mcp

    to_install: list[dict] = []
    skipped_merge: list[dict] = []
    skipped_deprecated: list[dict] = []
    skipped_already: list[dict] = []
    for d in dedup_report.get("decisions", []):
        cat = d.get("category", "")
        dec = d["decision"]
        if dec == "skip":
            skipped_already.append(d)
        elif dec == "merge":
            skipped_merge.append(d)  # 人工确认候选，不自动装
        elif dec == "new":
            if cat == "deprecated" and not include_deprecated:
                skipped_deprecated.append(d)
            else:
                to_install.append(d)

    target = Path(target_dir) if target_dir else (Path.home() / ".claude" / "skills")
    before = dedup_report.get("baseline", {}).get("counts", {}).get("distinct", 0)

    # dry-run 计划的 per-item 明细（形态/usability/凭证，反黑箱 D22）
    items_detail: list[dict] = []
    for d in to_install:
        name = d["name"]
        item = by_name.get(name, {})
        form = d.get("form") or item.get("form") or "Skill"
        usability = item.get("usability", "ready")
        entry: dict = {"name": name, "form": form, "usability": usability}
        if form == "MCP":
            mcp = item.get("mcp") or {}
            entry["scope"] = mcp.get("scope", "user")
            entry["transport"] = mcp.get("transport", "stdio")
            entry["command"] = mcp.get("command", "")
            entry["args"] = list(mcp.get("args") or [])  # 原样占位（<DIRS> 等），透明展示待改
            entry["credential_env"] = list(item.get("credential_env") or [])
            entry["needs_credentials"] = (usability == "needs_credentials")
        elif form == "repo":
            entry["repo"] = item.get("repo", "")
            entry["url"] = item.get("url", "")
            entry["install_method"] = item.get("install_method", "clone")
            entry["branch"] = item.get("default_branch", "main")
            entry["credential_env"] = list(item.get("credential_env") or [])
            entry["needs_credentials"] = (usability == "needs_credentials")
            entry["clone_target"] = str(config.repo_clones_dir() / name)
        else:
            entry["target"] = str(target / name)
            entry["file_count"] = len(item.get("files", []))
        items_detail.append(entry)

    plan = {
        "source_video": source_video,
        "verified_repo": full_name,
        "approve": approve,
        "target_dir": str(target),
        "before": before,
        "to_install": [d["name"] for d in to_install],
        "items_detail": items_detail,
        "skipped_merge": [d["name"] for d in skipped_merge],
        "skipped_deprecated": [d["name"] for d in skipped_deprecated],
        "skipped_already": [d["name"] for d in skipped_already],
        "unresolved": install_list.get("unresolved") or dedup_report.get("unresolved", []),
    }

    if not approve:
        plan["note"] = "dry-run：未下载、未注册、未写台账。加 --approve 才真装。"
        return plan

    # ---- 真装：按形态分发 + 登记 ----
    if any((d.get("form") or by_name.get(d["name"], {}).get("form")) == "Skill" for d in to_install):
        target.mkdir(parents=True, exist_ok=True)  # 仅 Skill 形态需要目标目录
    # db_path 默认 None → 用 registry 自己的 DB_PATH（别把 None 传进去盖掉默认值）
    conn = registry.connect(db_path if db_path is not None else registry.DB_PATH)
    installed: list[dict] = []
    skipped_credentials: list[dict] = []
    skipped_config: list[dict] = []
    try:
        total = len(to_install)
        for i, d in enumerate(to_install):
            name = d["name"]
            item = by_name.get(name, {})
            form = d.get("form") or item.get("form") or "Skill"
            if form == "MCP":
                usability = item.get("usability", "ready")
                # needs_credentials 且凭证未配 → 跳过真装，不替用户造凭证（D22）
                if usability == "needs_credentials" and not _credentials_configured(item):
                    skipped_credentials.append({
                        "name": name, "form": "MCP",
                        "credential_env": list(item.get("credential_env") or []),
                        "reason": "需凭证且环境未配置，跳过真装",
                    })
                    continue
                resolved_args, sub_dirs = _resolve_args(item.get("mcp") or {})
                # needs_config 且占位仍未解析 → 跳过，避免注册坏服务器
                if _has_unresolved_placeholder(resolved_args):
                    skipped_config.append({
                        "name": name, "form": "MCP",
                        "reason": "args 仍含未解析占位符 <…>，待配置后再装",
                    })
                    continue
                installed.append(_install_mcp(conn, item, d, source_video, full_name,
                                              resolved_args, sub_dirs,
                                              on_progress=on_progress, i=i, total=total))
            elif form == "repo":
                # repo：克隆+装依赖即安装，needs_credentials 不跳过（key 只在跑时才用）
                installed.append(_install_repo(conn, item, d, source_video, full_name,
                                               on_progress=on_progress, i=i, total=total))
            else:
                installed.append(
                    _install_skill(conn, item, d, target, source_video, full_name,
                                   on_progress=on_progress, i=i, total=total)
                )

        after = before + len(installed)
        registry.record_session(
            conn,
            session_id=f"{source_video}-{_now_iso()}",
            source_video=source_video,
            authorization_choice="install --approve",
            skills_before=before,
            skills_added=len(installed),  # 计所有已装能力（Skill + MCP，零 migration，列名语义泛化为「能力」）
            skills_merged=0,
            skills_after=after,
            installed_at=_now_iso(),
            notes=(
                f"装 {len(installed)} 个新能力；跳过 merge {len(skipped_merge)}/"
                f"deprecated {len(skipped_deprecated)}/已装 {len(skipped_already)}/"
                f"需凭证 {len(skipped_credentials)}/需配置 {len(skipped_config)}"
            ),
        )
    finally:
        conn.close()

    plan["installed"] = installed
    plan["skipped_credentials"] = skipped_credentials
    plan["skipped_config"] = skipped_config
    plan["after"] = after
    forms: dict[str, int] = {}
    for it in installed:
        f = it.get("form", "Skill")
        forms[f] = forms.get(f, 0) + 1
    forms_str = " ".join(f"{k}={v}" for k, v in forms.items()) or "—"
    note = f"已落盘 {len(installed)} 个能力（{forms_str}），并登记进台账。"
    if skipped_credentials:
        note += f" 需凭证跳过 {len(skipped_credentials)} 个，待配 credential_env 后重跑。"
    if skipped_config:
        note += f" 需配置跳过 {len(skipped_config)} 个，待替换占位符后重跑。"
    plan["note"] = note
    return plan


def format_plan_text(r: dict) -> str:
    """把 install 报告格式化成人读多行文本（dry-run 与真装通用，形态分发文案）。

    cli.cmd_install 与本模块 _main 共用，保两入口输出一致。
    """
    # 落点按本次实际形态列（反黑箱 D22）：Skill→skills 目录、MCP→注册 ~/.claude.json、
    # repo→克隆目录。混合形态则都列出，避免 repo 项误显示成 skills 目录。
    forms = {it.get("form", "Skill") for it in (r.get("items_detail") or [])}
    targets = []
    if "Skill" in forms or not forms:
        targets.append(str(r.get("target_dir", "")))
    if "MCP" in forms:
        targets.append("注册 ~/.claude.json")
    if "repo" in forms:
        targets.append(f"克隆 {config.repo_clones_dir()}")
    target_line = " + ".join(targets) or str(r.get("target_dir", ""))
    lines = [
        f"源视频：{r['source_video']}  仓库：{r['verified_repo'] or '(未知)'}",
        f"目标/注册：{target_line}  安装前 distinct：{r['before']}",
        f"将装 new：{len(r['to_install'])} 个",
    ]
    for it in r.get("items_detail") or []:
        form = it.get("form", "Skill")
        tag = ""
        if it.get("needs_credentials"):
            if form == "repo":
                envs = ",".join(it.get("credential_env", [])) or "credential_env"
                tag = f"  〔跑时需凭证 {envs}（克隆+装依赖照常进行）〕"
            else:  # MCP 需凭证（如 github PAT）→ 装了也不能起，默认跳过真装
                tag = "  ⚠️ 需凭证（默认跳过真装，待配 credential_env）"
        elif it.get("usability") and it["usability"] != "ready":
            tag = f"  〔装完前必做：{it['usability']}〕"
        if form == "MCP":
            args = " ".join(it.get("args", []))
            head = (f"  - [{form}] {it['name']}  scope={it.get('scope','user')}  "
                    f"{it.get('command','')} {args}".rstrip())
            lines.append(head + tag)
        elif form == "repo":
            lines.append(
                f"  - [{form}] {it['name']}  {it.get('repo','')}  → {it.get('clone_target','')}"
                f"（git clone --branch {it.get('branch','main')}）{tag}".rstrip()
            )
        else:
            lines.append(
                f"  - [{form}] {it['name']}  → {it.get('target','')}"
                f"（{it.get('file_count',0)} 文件）{tag}".rstrip()
            )
    if r.get("skipped_merge"):
        lines.append(f"跳过 merge（人工确认）：{len(r['skipped_merge'])} 个 → {r['skipped_merge']}")
    if r.get("skipped_deprecated"):
        lines.append(f"跳过 deprecated：{len(r['skipped_deprecated'])} 个 → {r['skipped_deprecated']}（--include-deprecated 可装）")
    if r.get("skipped_already"):
        lines.append(f"跳过已装/已整并：{len(r['skipped_already'])} 个")
    sc = r.get("skipped_credentials") or []
    if sc:
        lines.append(f"跳过需凭证（待配 credential_env）：{[s['name'] for s in sc]}")
    scfg = r.get("skipped_config") or []
    if scfg:
        lines.append(f"跳过需配置（占位符未解析）：{[s['name'] for s in scfg]}")
    if r.get("unresolved"):
        names = [u.get("name") for u in r["unresolved"]]
        lines.append(f"unresolved（catalog miss，待定夺，不自动包装）：{names}")
    return "\n".join(lines)


# ---- 直接运行：python -m skillbrew.install <源目录> [--approve] ----
def _main() -> int:
    import sys
    if len(sys.argv) < 2:
        print("用法: python -m skillbrew.install <源目录> [--approve] [--include-deprecated] [--target-dir DIR]")
        print("     源目录需含 install_list.json + dedup.json（先跑 verify、dedup）")
        return 1
    src = Path(sys.argv[1])
    approve = "--approve" in sys.argv
    include_dep = "--include-deprecated" in sys.argv
    target = None
    if "--target-dir" in sys.argv:
        target = sys.argv[sys.argv.index("--target-dir") + 1]
    print(f"[安装] {src}  {'真装' if approve else 'dry-run'}")
    r = install(src, target_dir=target, approve=approve, include_deprecated=include_dep)
    print("\n" + "=" * 60)
    print(format_plan_text(r))
    print("=" * 60)
    if approve:
        installed = r.get("installed", [])
        print(f"\n✅ 已落盘 {len(installed)} 个能力，安装后 distinct：{r.get('after')}")
        for s in installed:
            if s.get("form") == "MCP":
                dirs = "  〔<DIRS> 已填默认目录，建议收窄〕" if s.get("dirs_filled") else ""
                print(f"  - {s['name']}（{s.get('registered_via','')}，scope={s.get('scope','')}，"
                      f"usability={s.get('usability','')}）→ {s.get('path','')}{dirs}")
            elif s.get("form") == "repo":
                cloned = "新克隆" if s.get("cloned_now") else "已存在(幂等跳过)"
                deps = "依赖✅" if s.get("deps_installed") else f"依赖待补({s.get('deps_method','none')})"
                print(f"  - {s['name']}（{s.get('repo','')}@{s.get('branch','main')}，{cloned}，{deps}，"
                      f"usability={s.get('usability','')}）→ {s.get('path','')}")
            else:
                print(f"  - {s['name']}（{s.get('file_count',0)} 文件）→ {s.get('path','')}")
        print(f"   {r.get('note', '')}")
    else:
        print("\n   " + r.get("note", ""))
        print("   加 --approve 才真落盘 + 写台账。")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
