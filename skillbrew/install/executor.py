"""install 包的执行编排：形态分发安装、主入口 install()、dry-run/真装 CLI。

子模块划分：
- utils.py: 通用小工具（_fetch_bytes / _now_iso / _rel_within + UA/_TIMEOUT 等常量）
- resolver.py: 纯决策/解析（凭证判定、args 占位替换、MCP server 配置、deps 探测）
- mcp_toml.py: Codex TOML 文本级段替换工具（不做全量 TOML 解析）
- spec.py: D23 通用安装器（推断/验证/补全/缓存，原 installer.py 的主体）
- executor.py（本文件）: 形态分发安装 + 主流程 install() + CLI _main()
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import warnings
from pathlib import Path

from .. import config, installer, registry
from ..recommend import V_WORTH
from ..verify import parse_frontmatter  # 复用 SKILL.md frontmatter 轻量解析
from . import utils as _utils
from .mcp_toml import (
    _toml_read_mcp_server,
    _toml_render_mcp_server,
    _toml_replace_mcp_server,
)
from .resolver import (
    _credentials_configured,
    _detect_deps_method,
    _has_unresolved_placeholder,
    _inject_env,
    _mcp_server_config,
    _resolve_args,
)

# 以下几个公共符号走「install 包对象自身」的 late binding——
# 测试会 monkeypatch.setattr(install_mod, "_fetch_bytes", ...) 这种包属性，
# 只有通过包对象取才能看到 patch；直接 from-import 会拿到模块内绑定，patch 不生效。
# _install_pkg 在函数第一次调用时被解析（此时 install 包 __init__.py 已执行完、包对象就位）。
_INSTALL_PKG = sys.modules[__package__]  # type: ignore[index]
# 常量（不可变、不被 patch）直接从 utils 拿
UA = _utils.UA
_MAX_RETRIES = _utils._MAX_RETRIES
_RETRY_BACKOFF = _utils._RETRY_BACKOFF
_TIMEOUT = _utils._TIMEOUT


def _fetch_bytes(url):
    return _INSTALL_PKG._fetch_bytes(url)


def _now_iso():
    return _utils._now_iso()


def _rel_within(skill_dir_path, file_path):
    return _utils._rel_within(skill_dir_path, file_path)


# 阿里云 PyPI 镜像：云电脑直连 pypi 慢、易 hang 死，统一走镜像
_PIP_MIRROR_ARGS = [
    "-i",
    "https://mirrors.aliyun.com/pypi/simple/",
    "--trusted-host",
    "mirrors.aliyun.com",
]

# 装依赖给宽裕超时：重依赖（torch/moviepy/faster-whisper 等）装包远慢于网络探测
_DEPS_INSTALL_TIMEOUT = _TIMEOUT * 40  # 1200s ≈ 20min


# ==================== 形态分发：Skill 整目录拷 ====================


def _install_skill(
    conn,
    item: dict,
    decision: dict,
    target: Path,
    source_video: str,
    full_name: str,
    on_progress=None,
    i: int = 0,
    total: int = 1,
) -> dict:
    """Skill 形态：整目录从 GitHub raw 拷到 target/<name>/，登记台账。"""
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
            except Exception:  # noqa: BLE001
                pass
    registry.upsert_skill(
        conn,
        name,
        display_name=display_name,
        category=item.get("category", decision.get("category", "")),
        form=item.get("form", "Skill"),
        source=full_name,
        source_video=source_video,
        install_path=str(dest_dir),
        file_count=n_files,
        status="active",
        attribution=f"{full_name}（GitHub 开源）",
        dedup_note="dedup 判定 new，从 GitHub raw 逐文件下载安装",
        installed_at=_now_iso(),
    )
    return {
        "name": name,
        "display_name": display_name,
        "form": "Skill",
        "file_count": n_files,
        "path": str(dest_dir),
    }


# ==================== 形态分发：MCP 注册 ====================


def _install_mcp_cli(
    bin_path: str, name: str, item: dict, scope: str, transport: str, resolved_args: list[str]
) -> dict:
    """CLI-first：`claude mcp add` 注册。stdio 用 `--` 分隔 command/args，http/sse 用 -t。"""
    mcp = item.get("mcp") or {}
    cmd = [bin_path, "mcp", "add"]
    if transport in ("http", "sse"):
        cmd += ["-s", scope, "-t", transport, name, mcp.get("url", "")]
        for h in mcp.get("headers") or []:
            cmd += ["-H", h]
    else:  # stdio
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
    getp = subprocess.run(
        [bin_path, "mcp", "get", name], capture_output=True, text=True, timeout=_TIMEOUT
    )
    if getp.returncode != 0 and name not in (getp.stdout + getp.stderr):
        raise RuntimeError(
            f"claude mcp add 后 get 不到 {name}: {(getp.stderr or getp.stdout).strip()}"
        )
    return {
        "registered_via": "cli",
        "install_path": f"~/.claude.json:mcpServers/{name} (scope={scope})",
    }


def _install_mcp_json_merge(
    name: str, item: dict, scope: str, transport: str, resolved_args: list[str]
) -> dict:
    """无 claude binary 时 fallback：原子合并进 ~/.claude.json（user/local）或 ./.mcp.json（project）。"""
    server = _mcp_server_config(item, resolved_args)

    if scope == "project":
        pm = Path.cwd() / ".mcp.json"
        pdata: dict = {}
        if pm.exists():
            try:
                pdata = json.loads(pm.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                try:
                    corrupt = pm.read_bytes()
                    bak = pm.with_name(pm.name + ".bak")
                    bak.write_bytes(corrupt)
                except Exception:  # noqa: BLE001
                    pass
                warnings.warn(
                    f"项目级 .mcp.json 损坏无法解析，已备份为 {pm.name}.bak 并从空重建：{e}",
                    stacklevel=2,
                )
                pdata = {}
        pdata.setdefault("mcpServers", {})[name] = server
        pm.write_text(json.dumps(pdata, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "registered_via": "json-merge",
            "install_path": f"{pm}:mcpServers/{name} (scope=project)",
        }

    cj = config.claude_json_path()
    bak = cj.with_suffix(cj.suffix + ".bak")

    def _read() -> dict:
        if not cj.exists():
            return {}
        try:
            return json.loads(cj.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            warnings.warn(
                f"~/.claude.json 损坏无法解析，已备份为 .bak 并从空重建（其它 MCP 配置将丢失，需手工合并）：{e}",
                stacklevel=2,
            )
            return {}

    data = _read()
    mtime0 = cj.stat().st_mtime if cj.exists() else None
    if cj.exists():
        bak.write_bytes(cj.read_bytes())

    if scope == "user":
        data.setdefault("mcpServers", {})[name] = server
    elif scope == "local":
        cwd = str(Path.cwd())
        data.setdefault("projects", {}).setdefault(cwd, {}).setdefault("mcpServers", {})[name] = (
            server
        )
    else:
        raise RuntimeError(f"未知 MCP scope: {scope}")

    if cj.exists() and cj.stat().st_mtime != mtime0:
        fresh = _read()
        if scope == "user":
            fresh.setdefault("mcpServers", {})[name] = server
        else:
            fresh.setdefault("projects", {}).setdefault(str(Path.cwd()), {}).setdefault(
                "mcpServers", {}
            )[name] = server
        data = fresh

    cj.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        json.loads(cj.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        if bak.exists():
            cj.write_bytes(bak.read_bytes())
        raise RuntimeError(f"~/.claude.json 写后校验失败，已回滚 .bak：{name}")
    return {
        "registered_via": "json-merge",
        "install_path": f"~/.claude.json:mcpServers/{name} (scope={scope})",
    }


def _install_mcp_toml_merge(
    name: str, item: dict, scope: str, transport: str, resolved_args: list[str]
) -> dict:
    """Codex 运行时 fallback：文本级段替换写进 ~/.codex/config.toml（user scope）。

    不做全量 TOML 解析——只切出 ``[mcp_servers.<name>]`` 段替换，其它 section/注释/空白原样保留。
    project scope 暂不支持（当前版本先按 user scope 写全局，行为透明报告）。
    """
    server = _mcp_server_config(item, resolved_args)
    if scope == "project":
        scope = "user"

    cj = config.claude_json_path()
    cj.parent.mkdir(parents=True, exist_ok=True)
    bak = cj.with_suffix(cj.suffix + ".bak")

    def _read_text() -> str:
        if not cj.exists():
            return ""
        return cj.read_text(encoding="utf-8")

    text = _read_text()
    mtime0 = cj.stat().st_mtime if cj.exists() else None
    if cj.exists():
        bak.write_bytes(cj.read_bytes())

    block = _toml_render_mcp_server(name, server)
    new_text = _toml_replace_mcp_server(text, name, block)

    if cj.exists() and cj.stat().st_mtime != mtime0:
        fresh = _read_text()
        new_text = _toml_replace_mcp_server(fresh, name, block)

    cj.write_text(new_text, encoding="utf-8")
    try:
        readback = _toml_read_mcp_server(cj.read_text(encoding="utf-8"), name)
        if readback is None:
            raise RuntimeError(f"写后读回找不到 [mcp_servers.{name}] 段")
        if server.get("command") and readback.get("command") != server["command"]:
            raise RuntimeError(
                f"写后读回 command 不一致：{readback.get('command')!r} != {server['command']!r}"
            )
        if "args" in server and readback.get("args") != server["args"]:
            raise RuntimeError(
                f"写后读回 args 不一致：{readback.get('args')!r} != {server['args']!r}"
            )
        if server.get("env"):
            if readback.get("env") != server["env"]:
                raise RuntimeError(
                    f"写后读回 env 不一致：{readback.get('env')!r} != {server['env']!r}"
                )
        if server.get("url") and readback.get("url") != server["url"]:
            raise RuntimeError(f"写后读回 url 不一致：{readback.get('url')!r} != {server['url']!r}")
    except Exception:  # noqa: BLE001
        if bak.exists():
            cj.write_bytes(bak.read_bytes())
        raise
    return {
        "registered_via": "toml-merge",
        "install_path": f"{cj}:[mcp_servers.{name}] (scope={scope})",
    }


def _install_mcp(
    conn,
    item: dict,
    decision: dict,
    source_video: str,
    full_name: str,
    resolved_args: list[str],
    substituted_dirs: bool,
    on_progress=None,
    i: int = 0,
    total: int = 1,
) -> dict:
    """注册一个 MCP 服务器 + 登记台账。CLI-first，无 binary 走原子 JSON 合并。"""
    name = decision["name"]
    if on_progress:
        on_progress(item, i, total)
    mcp = item.get("mcp") or {}
    scope = mcp.get("scope") or config.mcp_default_scope
    transport = (mcp.get("transport") or "stdio").lower()

    runtime = config.detect_runtime()
    if runtime == "codex":
        via = _install_mcp_toml_merge(name, item, scope, transport, resolved_args)
    else:
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
        conn,
        name,
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
    return {
        "name": name,
        "form": "MCP",
        "scope": scope,
        "transport": transport,
        "registered_via": via["registered_via"],
        "usability": usability,
        "dirs_filled": substituted_dirs,
        "path": via["install_path"],
    }


# ==================== 形态分发：repo 克隆即用 ====================


def _install_repo_deps(clone_dir: Path, method: str) -> dict:
    """按探测到的依赖清单装依赖（阿里云镜像防 hang）。返回 {installed, detail}。

    装依赖失败/超时都不抛——克隆已成功，依赖可后补。
    distutils 冲突自愈：首次失败若命中该错误，自动加 --ignore-installed 重试一次。
    """
    if method == "none":
        return {"installed": False, "detail": "未发现依赖清单，跳过装依赖"}
    if method == "npm":
        npm = shutil.which("npm")
        if not npm:
            return {"installed": False, "detail": "发现 package.json 但本机无 npm，跳过（可后补）"}
        cmd, label = [npm, "install"], "npm install"
        try:
            proc = subprocess.run(
                cmd, cwd=clone_dir, capture_output=True, text=True, timeout=_DEPS_INSTALL_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            return {
                "installed": False,
                "detail": f"{label} 超时（{_DEPS_INSTALL_TIMEOUT:.0f}s），克隆已成功、依赖可后补",
            }
        ok = proc.returncode == 0
        return {
            "installed": ok,
            "detail": f"{label} {'成功' if ok else '失败'}: {(proc.stderr or proc.stdout).strip()[:200]}",
        }

    base = [sys.executable, "-m", "pip", "install"]
    if method == "pip-requirements":
        base += ["-r", "requirements.txt"]
    else:  # pip-pyproject
        base += ["."]
    label = "pip install"

    def _run(extra_args):
        try:
            return subprocess.run(
                base + extra_args + _PIP_MIRROR_ARGS,
                cwd=clone_dir,
                capture_output=True,
                text=True,
                timeout=_DEPS_INSTALL_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return None

    proc = _run([])
    if proc is None:
        return {
            "installed": False,
            "detail": f"{label} 超时（{_DEPS_INSTALL_TIMEOUT:.0f}s），克隆已成功、依赖可后补",
        }
    if proc.returncode == 0:
        return {"installed": True, "detail": f"{label} 成功"}

    err = proc.stderr or proc.stdout or ""
    if "distutils" in err or "uninstall" in err:
        proc2 = _run(["--ignore-installed"])
        if proc2 is None:
            return {
                "installed": False,
                "detail": f"{label} 重试超时（{_DEPS_INSTALL_TIMEOUT:.0f}s），克隆已成功、依赖可后补",
            }
        if proc2.returncode == 0:
            return {
                "installed": True,
                "detail": f"{label} 成功（命中 distutils 卸载冲突，--ignore-installed 重试通过）",
            }
        err2 = (proc2.stderr or proc2.stdout or "").strip()[:200]
        return {
            "installed": False,
            "detail": f"{label} 失败（--ignore-installed 重试仍失败）: {err2}",
        }
    return {"installed": False, "detail": f"{label} 失败: {err.strip()[:200]}"}


def _install_repo(
    conn,
    item: dict,
    decision: dict,
    source_video: str,
    full_name: str,
    on_progress=None,
    i: int = 0,
    total: int = 1,
) -> dict:
    """repo 形态：git clone 到 config.repo_clones_dir()/<name>/ + 装依赖 + 登记台账。

    克隆即用（不改 ~/.claude/skills/）；needs_credentials 不跳过克隆（key 只在跑的时候才用）。
    已克隆过的目录幂等跳过 git clone（不覆盖本地改动）。
    """
    name = decision["name"]
    if on_progress:
        on_progress(item, i, total)
    repo_full = item.get("repo") or full_name
    url = item.get("url") or f"https://github.com/{repo_full}"
    branch = item.get("default_branch") or "main"
    clones_root = config.repo_clones_dir()
    clones_root.mkdir(parents=True, exist_ok=True)
    clone_dir = clones_root / name

    cloned_now = False
    if clone_dir.exists() and (clone_dir / ".git").exists():
        clone_detail = "已存在，跳过 git clone（幂等）"
    else:
        git_bin = shutil.which("git")
        if not git_bin:
            raise RuntimeError(f"本机无 git，无法克隆 {repo_full}（先装 git 再重跑）")
        proc = subprocess.run(
            [git_bin, "clone", "--depth", "1", "--branch", branch, url, str(clone_dir)],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT * 10,
        )
        if proc.returncode != 0:
            if clone_dir.exists():
                shutil.rmtree(clone_dir, ignore_errors=True)
            proc = subprocess.run(
                [git_bin, "clone", "--depth", "1", url, str(clone_dir)],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT * 10,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    f"git clone 失败 {repo_full}: {(proc.stderr or proc.stdout).strip()}"
                )
            clone_detail = f"git clone --depth 1 成功（记录分支 {branch} 不匹配，退回默认分支）"
        else:
            clone_detail = f"git clone --depth 1 --branch {branch} 成功"
        cloned_now = True

    deps_method = _detect_deps_method(clone_dir)
    deps = _install_repo_deps(clone_dir, deps_method)

    usability = item.get("usability", "ready")
    dedup_note = f"dedup 判定 new，{clone_detail}；{deps['detail']}"
    registry.upsert_skill(
        conn,
        name,
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
    return {
        "name": name,
        "form": "repo",
        "repo": repo_full,
        "install_method": "clone",
        "usability": usability,
        "path": str(clone_dir),
        "branch": branch,
        "deps_method": deps_method,
        "deps_installed": deps["installed"],
        "cloned_now": cloned_now,
    }


# ==================== 主流程 ====================


def install(
    source_dir: Path,
    *,
    target_dir: Path | str | None = None,
    db_path: Path | str | None = None,
    approve: bool = False,
    include_deprecated: bool = False,
    on_progress=None,
    ai_infer: bool = False,
    no_trial: bool = False,
    refresh_cache: bool = False,
    chat_fn=None,
    prompt_fn=None,
    on_resolve_progress=None,
) -> dict:
    """对一个源目录跑安装：读 install_list.json + dedup.json → 挑 new 按形态分发 → 登记台账。

    approve=False（默认）= dry-run，只返回计划，不下载/不注册/不写台账。
    approve=True = 真装 + upsert 台账 + 记会话。
    默认纯查表（GitHub raw + 标准库 + claude CLI，不调 LLM）；ai_infer 开时才对 unresolved
    的 MCP 跑「AI 推断装法 → 试跑验证 → 缺项补全」（D23）。

    on_progress(stage_item_dict, done, total)：实际安装每个能力前回调一次（既有行为）。
    on_resolve_progress(name, done, total, ok, reason)：AI 推断每个 unresolved 项回调一次，
        给 CLI 层做 spinner/进度（P1-3）。失败不影响主流程（defensive except）。
    """
    source_dir = Path(source_dir)
    il_path = source_dir / "install_list.json"
    dd_path = source_dir / "dedup.json"
    rec_path = source_dir / "recommend.json"
    if not il_path.exists():
        raise RuntimeError(f"没有 install_list.json，先跑 verify：{il_path}")
    if not dd_path.exists():
        raise RuntimeError(f"没有 dedup.json，先跑 dedup：{dd_path}")
    install_list = json.loads(il_path.read_text(encoding="utf-8"))
    dedup_report = json.loads(dd_path.read_text(encoding="utf-8"))

    approved_set: set[str] | None = None
    recommend_present = rec_path.exists()
    if recommend_present:
        rec_report = json.loads(rec_path.read_text(encoding="utf-8"))
        j_list = rec_report.get("judgments", [])
        approved_set = {j["name"] for j in j_list if j.get("verdict") == V_WORTH}

    repo = install_list.get("verified_repo", {})
    full_name = repo.get("full_name", "")
    source_video = install_list.get("source_video", source_dir.name)

    items = install_list.get("items") or install_list.get("skills", [])
    by_name = {s["name"]: s for s in items if s.get("name")}

    to_install: list[dict] = []
    skipped_merge: list[dict] = []
    skipped_deprecated: list[dict] = []
    skipped_already: list[dict] = []
    skipped_not_approved: list[dict] = []
    for d in dedup_report.get("decisions", []):
        cat = d.get("category", "")
        dec = d["decision"]
        if dec == "skip":
            skipped_already.append(d)
        elif dec == "merge":
            skipped_merge.append(d)
        elif dec == "new":
            if cat == "deprecated" and not include_deprecated:
                skipped_deprecated.append(d)
            elif approved_set is not None and d.get("name") not in approved_set:
                skipped_not_approved.append(d)
            else:
                to_install.append(d)

    target = Path(target_dir) if target_dir else config.skills_dir()
    before = dedup_report.get("baseline", {}).get("counts", {}).get("distinct", 0)

    unresolved = list(install_list.get("unresolved") or dedup_report.get("unresolved", []))
    resolve_traces: list[str] = []
    resolve_meta: dict[str, dict] = {}
    for name in by_name:
        resolve_meta[name] = {"provenance": "catalog", "trace": [], "missing": []}
    if ai_infer and unresolved:
        _r_total = len(unresolved)
        _r_done = 0
        for u in list(unresolved):
            name = u.get("name") or ""
            if not name:
                _r_done += 1
                continue
            _rr_ok = False
            _rr_reason = ""
            try:
                rr = installer.resolve_install_spec(
                    name,
                    repo=u.get("repo"),
                    url=u.get("url"),
                    allow_ai=ai_infer,
                    skip_trial=no_trial,
                    refresh_cache=refresh_cache,
                    has_tty=config.has_tty(),
                    chat_fn=chat_fn,
                    prompt_fn=prompt_fn,
                )
            except Exception as e:  # noqa: BLE001
                msg = f"[{name}] resolve 异常（留 unresolved）：{e}"
                resolve_traces.append(msg)
                warnings.warn(msg, stacklevel=2)
                _r_done += 1
                if on_resolve_progress is not None:
                    try:
                        on_resolve_progress(name, _r_done, _r_total, False, str(e)[:120])
                    except Exception:  # noqa: BLE001
                        pass
                continue
            for t in rr.trace or []:
                resolve_traces.append(f"[{name}] {t}")
            if rr.ok and rr.spec is not None:
                for var, val in (rr.filled or {}).items():
                    os.environ[var] = val
                item = installer.spec_to_item(rr.spec, source_ref=u.get("source_ref"))
                sanitized_name = item["name"]
                by_name[sanitized_name] = item
                to_install.append({"name": sanitized_name, "form": "MCP", "category": "new"})
                unresolved = [x for x in unresolved if x.get("name") != name]
                resolve_meta[sanitized_name] = {
                    "provenance": rr.provenance,
                    "trace": list(rr.trace or []),
                    "missing": list(rr.missing or []),
                }
                resolve_traces.append(
                    f"[{name}] resolve 成功：provenance={rr.provenance}，已纳入安装计划"
                )
                _rr_ok = True
                _rr_reason = f"ok ({rr.provenance})"
            else:
                if rr.reason:
                    resolve_traces.append(f"[{name}] resolve 未通过：{rr.reason}")
                    u["reason"] = rr.reason
                    _rr_reason = rr.reason[:120]
                if rr.missing:
                    u["missing"] = list(rr.missing)
            _r_done += 1
            if on_resolve_progress is not None:
                try:
                    on_resolve_progress(name, _r_done, _r_total, _rr_ok, _rr_reason)
                except Exception:  # noqa: BLE001
                    pass

    for u in unresolved:
        name = u.get("name") or ""
        if name:
            resolve_meta[name] = {
                "provenance": "unresolved",
                "trace": [],
                "missing": list(u.get("missing", [])),
                "reason": u.get("reason", ""),
            }
    _write_resolve_trace(source_dir, resolve_meta, unresolved)

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
            entry["args"] = list(mcp.get("args") or [])
            entry["credential_env"] = list(item.get("credential_env") or [])
            entry["needs_credentials"] = usability == "needs_credentials"
        elif form == "repo":
            entry["repo"] = item.get("repo", "")
            entry["url"] = item.get("url", "")
            entry["install_method"] = item.get("install_method", "clone")
            entry["branch"] = item.get("default_branch", "main")
            entry["credential_env"] = list(item.get("credential_env") or [])
            entry["needs_credentials"] = usability == "needs_credentials"
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
        "skipped_not_approved": [d["name"] for d in skipped_not_approved],
        "recommend_present": recommend_present,
        "unresolved": unresolved,
        "resolve_traces": resolve_traces,
    }

    if not approve:
        plan["note"] = "dry-run：未下载、未注册、未写台账。加 --approve 才真装。"
        return plan

    if any(
        (d.get("form") or by_name.get(d["name"], {}).get("form")) == "Skill" for d in to_install
    ):
        target.mkdir(parents=True, exist_ok=True)
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
                if usability == "needs_credentials" and not _credentials_configured(item):
                    skipped_credentials.append(
                        {
                            "name": name,
                            "form": "MCP",
                            "credential_env": list(item.get("credential_env") or []),
                            "reason": "需凭证且环境未配置，跳过真装",
                        }
                    )
                    continue
                resolved_args, sub_dirs = _resolve_args(item.get("mcp") or {})
                if _has_unresolved_placeholder(resolved_args):
                    skipped_config.append(
                        {
                            "name": name,
                            "form": "MCP",
                            "reason": "args 仍含未解析占位符 <…>，待配置后再装",
                        }
                    )
                    continue
                installed.append(
                    _install_mcp(
                        conn,
                        item,
                        d,
                        source_video,
                        full_name,
                        resolved_args,
                        sub_dirs,
                        on_progress=on_progress,
                        i=i,
                        total=total,
                    )
                )
            elif form == "repo":
                installed.append(
                    _install_repo(
                        conn,
                        item,
                        d,
                        source_video,
                        full_name,
                        on_progress=on_progress,
                        i=i,
                        total=total,
                    )
                )
            else:
                installed.append(
                    _install_skill(
                        conn,
                        item,
                        d,
                        target,
                        source_video,
                        full_name,
                        on_progress=on_progress,
                        i=i,
                        total=total,
                    )
                )

        after = before + len(installed)
        registry.record_session(
            conn,
            session_id=f"{source_video}-{_now_iso()}",
            source_video=source_video,
            authorization_choice="install --approve",
            skills_before=before,
            skills_added=len(installed),
            skills_merged=0,
            skills_after=after,
            installed_at=_now_iso(),
            notes=(
                f"装 {len(installed)} 个新能力；跳过 merge {len(skipped_merge)}/"
                f"deprecated {len(skipped_deprecated)}/已装 {len(skipped_already)}/"
                f"不值得装 {len(skipped_not_approved)}/"
                f"需凭证 {len(skipped_credentials)}/需配置 {len(skipped_config)}"
                f"{'（recommend 过滤生效）' if recommend_present else '（无 recommend.json，旧行为）'}"
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


# ==================== add：通用 MCP 注册（issue #27 Phase 2） ====================


def _normalize_transport(t: str | None) -> str:
    """归一化连接方式：http/https/streamable-http → http；sse → sse；其余 → stdio。

    与 _mcp_server_config 的分流保持一致（它只认 http/sse，其余按 stdio 处理），
    兼容 Smithery 返回的 ``streamable-http`` 写法。
    """
    t = (t or "stdio").lower()
    if t in ("http", "https", "streamable-http", "streamable_http"):
        return "http"
    if t == "sse":
        return "sse"
    return "stdio"


def _mask_server(server: dict) -> dict:
    """脱敏 server 预览：env/headers 的值换成 ``<KEY>``，只留键名（dry-run 展示用，D14 不泄密）。"""
    out = dict(server)
    env = out.get("env")
    if isinstance(env, dict):
        out["env"] = {k: f"<{k}>" for k in env}
    hdrs = out.get("headers")
    if isinstance(hdrs, dict):
        out["headers"] = {k: f"<{k}>" for k in hdrs}
    return out


def register_mcp(
    name: str,
    *,
    transport: str = "stdio",
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    env_keys: list[str] | None = None,
    headers: dict[str, str] | None = None,
    scope: str | None = None,
    source: str = "",
    approve: bool = False,
    db_path: Path | str | None = None,
) -> dict:
    """注册一个 MCP 服务器进配置文件 + 登记台账（``add`` 命令后端，issue #27 Phase 2）。

    通用原语：连接方式（transport）驱动——http/sse 走远程 URL，stdio 走本地命令；
    不绑死任何市场（手动 URL/命令 或 从 Smithery 拉都行，Smithery 只是 CLI 层的可选解析器）。

    复用 install 的写入器（_install_mcp_json_merge / _install_mcp_toml_merge：原子备份 +
    mtime 并发检测 + 写后校验 + 失败回滚）和 registry 台账，不新造写入轮子。走「合并路径」
    写配置（不调 claude CLI），跨运行时：Claude 写 ~/.claude.json，Codex 写 ~/.codex/config.toml。

    - approve=False（默认）= dry-run：返回将写的 server 预览（env/headers 已脱敏），不落盘、
      不登台账（反盲盒 D22）。
    - approve=True = 真写 + upsert 台账 + 记会话。

    env_keys 声明依赖的环境变量名，值从 os.environ 取（跟 install 凭证模型一致 D14，
    secret 不进命令行 / 台账）；headers 直接给值（HTTP 头，写进配置）。
    """
    if not (name or "").strip():
        raise RuntimeError("add 需要一个 MCP 名（注册 key）")
    name = name.strip()
    tport = _normalize_transport(transport)
    scope = (scope or config.mcp_default_scope).strip().lower()

    mcp: dict = {"transport": tport}
    if tport in ("http", "sse"):
        if not url:
            raise RuntimeError(f"{tport} 需要 url（远程地址）")
        mcp["url"] = url
        if headers:
            mcp["headers"] = dict(headers)
        resolved_args: list[str] = []
        sub_dirs = False
    else:  # stdio
        if not command:
            raise RuntimeError("stdio 需要 command（本地命令）")
        mcp["command"] = command
        mcp["args"] = list(args or [])
        resolved_args, sub_dirs = _resolve_args(mcp)
        if _has_unresolved_placeholder(resolved_args):
            raise RuntimeError("args 仍含未解析占位符 <…>，替换后再装")

    env_keys = list(env_keys or [])
    item: dict = {"mcp": mcp, "form": "MCP", "capability_name": name}
    if env_keys:
        # _inject_env 收 credential_env + env_template.keys()，值从 os.environ 取
        item["env_template"] = {k: "" for k in env_keys}
        item["credential_env"] = list(env_keys)
    missing_env = [k for k in env_keys if not os.environ.get(k)]

    server_preview = _mask_server(_mcp_server_config(item, resolved_args))

    if not approve:
        return {
            "name": name,
            "form": "MCP",
            "transport": tport,
            "scope": scope,
            "approve": False,
            "server": server_preview,
            "path": "(dry-run 未落盘)",
            "missing_env": missing_env,
            "note": "dry-run：未写配置、未登台账。加 --approve 才真装。",
        }

    runtime = config.detect_runtime()
    if runtime == "codex":
        via = _install_mcp_toml_merge(name, item, scope, tport, resolved_args)
    else:
        via = _install_mcp_json_merge(name, item, scope, tport, resolved_args)

    conn = registry.connect(db_path if db_path is not None else registry.DB_PATH)
    try:
        before_row = conn.execute("SELECT COUNT(*) FROM skills WHERE status='active'").fetchone()
        before = int(before_row[0]) if before_row else 0
        registry.upsert_skill(
            conn,
            name,
            display_name=name,
            category="",
            form="MCP",
            source=source or name,
            source_video="",
            install_path=via["install_path"],
            file_count=0,
            status="active",
            attribution=source or f"manual add（{tport}）",
            dedup_note=f"add 命令注册（{tport}，scope={scope}）",
            installed_at=_now_iso(),
        )
        registry.record_session(
            conn,
            session_id=f"add-{name}-{_now_iso()}",
            source_video="",
            authorization_choice="add --approve",
            skills_before=before,
            skills_added=1,
            skills_merged=0,
            skills_after=before + 1,
            installed_at=_now_iso(),
            notes=f"add 注册 MCP {name}（{tport}，scope={scope}）",
        )
    finally:
        conn.close()

    return {
        "name": name,
        "form": "MCP",
        "transport": tport,
        "scope": scope,
        "approve": True,
        "registered_via": via["registered_via"],
        "path": via["install_path"],
        "server": server_preview,
        "missing_env": missing_env,
        "dirs_filled": sub_dirs,
    }


def format_plan_text(r: dict) -> str:
    """把 install 报告格式化成人读多行文本（dry-run 与真装通用，形态分发文案）。"""
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
    ]
    if r.get("recommend_present"):
        lines.append(f"将装 new（已按 recommend.approved 过滤）：{len(r['to_install'])} 个")
    else:
        lines.append(f"将装 new（无 recommend.json，旧行为：全装 new）：{len(r['to_install'])} 个")
    for it in r.get("items_detail") or []:
        form = it.get("form", "Skill")
        tag = ""
        if it.get("needs_credentials"):
            if form == "repo":
                envs = ",".join(it.get("credential_env", [])) or "credential_env"
                tag = f"  〔跑时需凭证 {envs}（克隆+装依赖照常进行）〕"
            else:
                tag = "  ⚠️ 需凭证（默认跳过真装，待配 credential_env）"
        elif it.get("usability") and it["usability"] != "ready":
            tag = f"  〔装完前必做：{it['usability']}〕"
        if form == "MCP":
            args = " ".join(it.get("args", []))
            head = (
                f"  - [{form}] {it['name']}  scope={it.get('scope', 'user')}  "
                f"{it.get('command', '')} {args}".rstrip()
            )
            lines.append(head + tag)
        elif form == "repo":
            lines.append(
                f"  - [{form}] {it['name']}  {it.get('repo', '')}  → {it.get('clone_target', '')}"
                f"（git clone --branch {it.get('branch', 'main')}）{tag}".rstrip()
            )
        else:
            lines.append(
                f"  - [{form}] {it['name']}  → {it.get('target', '')}"
                f"（{it.get('file_count', 0)} 文件）{tag}".rstrip()
            )
    if r.get("skipped_merge"):
        lines.append(f"跳过 merge（人工确认）：{len(r['skipped_merge'])} 个 → {r['skipped_merge']}")
    if r.get("skipped_deprecated"):
        lines.append(
            f"跳过 deprecated：{len(r['skipped_deprecated'])} 个 → {r['skipped_deprecated']}（--include-deprecated 可装）"
        )
    if r.get("skipped_already"):
        lines.append(f"跳过已装/已整并：{len(r['skipped_already'])} 个")
    sna = r.get("skipped_not_approved") or []
    if sna:
        lines.append(f"跳过 recommend 判「不值得装」：{len(sna)} 个 → {sna}")
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


def _write_resolve_trace(
    source_dir: Path, resolve_meta: dict[str, dict], unresolved: list[dict]
) -> None:
    """写 resolve_trace.json sidecar：每项 provenance/trace/missing + unresolved 列表。"""
    rt = {
        "items": resolve_meta,
        "unresolved": unresolved,
    }
    rt_path = source_dir / "resolve_trace.json"
    rt_path.write_text(json.dumps(rt, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- 直接运行：python -m skillbrew.install <源目录> [--approve] ----


def _main() -> int:
    if len(sys.argv) < 2:
        print(
            "用法: python -m skillbrew.install <源目录> [--approve] [--include-deprecated] [--target-dir DIR]"
        )
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
                print(
                    f"  - {s['name']}（{s.get('registered_via', '')}，scope={s.get('scope', '')}，"
                    f"usability={s.get('usability', '')}）→ {s.get('path', '')}{dirs}"
                )
            elif s.get("form") == "repo":
                cloned = "新克隆" if s.get("cloned_now") else "已存在(幂等跳过)"
                deps = (
                    "依赖✅"
                    if s.get("deps_installed")
                    else f"依赖待补({s.get('deps_method', 'none')})"
                )
                print(
                    f"  - {s['name']}（{s.get('repo', '')}@{s.get('branch', 'main')}，{cloned}，{deps}，"
                    f"usability={s.get('usability', '')}）→ {s.get('path', '')}"
                )
            else:
                print(f"  - {s['name']}（{s.get('file_count', 0)} 文件）→ {s.get('path', '')}")
        print(f"   {r.get('note', '')}")
    else:
        print("\n   " + r.get("note", ""))
        print("   加 --approve 才真落盘 + 写台账。")
    return 0
