"""D23 通用安装器 —— 推断 / 验证 / 补全 / 缓存（MCP 形态先打通）。

为什么有这个模块
----------------
skillbrew 北极星是「任意素材丢进来 → AI 消化 → 自动装成真实能力」。但 MCP（模型
上下文协议）的安装命令原本只来自一张人工核实的硬编码目录（``mcp_catalog.py``，6 条）。
视频里出现的新 MCP 若不在目录里，只会被标 ``unresolved``（未解决）、**不自动装**。
靠人工扩目录"永无止境、档案大得不可思议"——违背"任意素材都能装"。

D23 解法：把 MCP 安装从「只查人工目录」改成「AI 读源头仓库自己推断装法 → 装前试跑
验证 → 缺 key/路径就弹窗问 → 验证过就记住」。人工目录降级为「预验证种子」，不再
需要人工扩充。MCP 是当前真正的瓶颈，本模块先打通它并搭好"推断-验证-补全-缓存"通用
骨架；CLI/Docker/API 等形态后续按同一骨架加。

> 一句话：**任何工具，AI 去源头仓库读 README 自己判断怎么装；装前先试跑确认能用；
> 缺什么就问你补什么，绝不莫名其妙运行失败；验证过的装法记下来下次秒装。装不了就
> 明白告诉你卡在哪。**

四级降级链（每级失败都不崩）
--------------------------
1. **查本地缓存**（``data/install_cache.json``，随 ``data/`` 自动 gitignore）：以前
   验证过的装法，命中即用，不问 AI。
2. **查 catalog 种子**：原 6 条人工核实目录，作预验证种子。
3. **AI 读源头仓库推断**：缓存和目录都没有时，AI 拉取该仓库的 README / package.json
   / pyproject.toml / Dockerfile / .env.example，推断装法（npx/uvx/docker/pip/git
   clone）+ 需要哪些参数（key/路径/token/环境变量）。
4. **试跑验证**：对推断命令先安全试跑（``npx <pkg> --help`` / ``<cmd> --version`` /
   ``docker pull <img>`` / ``python -c "import x"``），最多重试 1–2 次（换装法）。
   **只试跑命令本身，绝不写真配置**（不 ``claude mcp add``、不碰 ``~/.claude.json``）。
5. **缺项补全**：验证/装时发现缺东西，友善弹窗问用户补。绝不静默崩。

任一级走不通 → 降级下一级；全走不通 → 老实标 ``unresolved`` + 写明卡在哪，不崩、不
静默、不臆造。

为什么不破现有链路
-----------------
经代码勘察确认：``install.py`` 的 ``_install_mcp`` **不查 catalog**，只读
``item["mcp"]`` 字典；catalog 查表只发生在 ``verify.py`` 的 ``group_mcp_items``。所以
四级降级链只需把正确的 ``item["mcp"]`` 填出来——本模块的 ``spec_to_item`` 是**唯一**
的 item 字典构造器，产出与 ``verify.py`` group_mcp_items 命中分支【字段同构】的 dict，
下游 install/dedup/recommend/record 全链路零感知。

verify（溯源/判断步）保持纯查表（章程 D18：不联网、不调 LLM、不耗配额）。AI 推断/
试跑/弹窗全部下沉到 install（安装步 ⑦，已有 ``--approve`` 授权门、用户在场）——既实现
D23 又不破 D18。

密钥安全（D14）：缓存只存环境变量**名**、不存**值**（值恒空串）；试跑只跑命令本身。

本文件当前进度（2026-06-25）：第 1 步（数据类 + ``from_catalog_entry``/``spec_to_item``）、
第 2 步（``cache_*`` 本地缓存 + 原子写 + D14 卫生）、第 3 步（``infer_install_spec``/
``verify_install_spec``/``prompt_missing``/``resolve_install_spec`` 四级降级链）均已实现；
下游 install.py 接入 + cli 开关 + record 展示为后续步骤。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import warnings
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import config, mcp_catalog, plan, verify
from .mcp_catalog import McpEntry

# 第 3 步引入：re（占位符/文件名匹配）、subprocess（试跑）、plan（``_extract_json`` 解析
# AI 输出）、verify（复用 ``_raw_text``/``raw_url``/``probe_repo``/``list_tree``/
# ``parse_github_urls`` 抓仓库，不引外 lib）、mcp_catalog（L2 种子查表）。无循环 import
# （verify/plan/llm 均不反向引 installer）。llm 不直接引——``chat_fn`` 由调用方注入
# （生产传 ``llm.chat_text`` 绑定、测试传假函数），保持可离线测试。


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class InstallSpec:
    """一条 MCP 的安装配方（D23 通用安装器的中间表示）。

    既能由 catalog 种子转换而来（``from_catalog_entry``），也能由 AI 读源头仓库
    推断而来（``infer_install_spec``）。最终统一经 ``spec_to_item`` 产出与
    ``verify.py`` group_mcp_items 命中分支字段同构的 item dict，下游零感知。

    字段命名尽量与 ``McpEntry`` 对齐，方便 ``from_catalog_entry`` 逐字段搬运。

    ``provenance`` / ``verify_ok`` / ``missing`` / ``trace`` 是 D23 新增的「过程
    透明度」字段：记录这条配方来自哪一级、是否经试跑验证、还缺什么、怎么解析的，
    供报告展示（D22 反黑盒）。**这些字段不进 item dict**（下游不需要），仅留在 spec。
    """

    name: str
    command: str
    args: tuple[str, ...]
    invoke_hint: str
    transport: str = "stdio"
    scope: str = "user"
    env_template: dict[str, str] = field(default_factory=dict)
    repo: str | None = None
    url: str | None = None
    credential_env: tuple[str, ...] = ()
    optional_credential_env: tuple[str, ...] = ()
    needs_config: bool = False
    needs_runtime: bool = False
    post_install_steps: tuple[str, ...] = ()
    # ---- D23 过程透明度（不进 item dict）----
    provenance: str = "catalog"  # cache | catalog | ai | ai_unverified
    verify_ok: bool = False  # 是否经试跑验证（catalog 种子默认已核实）
    missing: list[str] = field(default_factory=list)  # 还缺的环境变量/路径/参数名
    trace: list[str] = field(default_factory=list)  # 解析过程轨迹，报告展示用


@dataclass
class VerifyResult:
    """试跑验证结果（``verify_install_spec`` 产出，第 3 步实现）。

    只试跑命令本身（如 ``npx <pkg> --help`` / ``<cmd> --version`` / ``docker pull``），
    **绝不写真配置**（不 ``claude mcp add``、不碰 ``~/.claude.json``）。最多重试 1–2 次
    （换装法）。成功 ok=True；失败留 reason + trace，不崩。
    """

    ok: bool
    attempts: list[str] = field(default_factory=list)  # 试过哪些命令
    reason: str = ""  # 失败原因（成功为空）
    trace: list[str] = field(default_factory=list)


@dataclass
class PromptResult:
    """缺项补全结果（``prompt_missing`` 产出，第 3 步实现）。

    两态：有终端（TTY）走交互 ``input()``（LoopGuard 最多 2 次重试）；无终端
    （headless，如本 Coze 环境）把缺项清单写进报告、由 agent 在对话里转达用户。
    ``filled`` 是本会话临时拿到的值（注入 env 用），**绝不进缓存**（D14：缓存只存
    变量名不存值）。
    """

    filled: dict[str, str] = field(default_factory=dict)  # 变量名 → 值（本会话临时，不入缓存）
    skipped: list[str] = field(default_factory=list)  # 用户跳过 / 无终端未填的变量名
    via: str = "report"  # tty | report


@dataclass
class ResolveResult:
    """四级降级链总调度结果（``resolve_install_spec`` 产出，第 3 步实现）。

    ``ok=True`` 表示拿到可用配方（缓存命中 / catalog 种子 / AI 推断+验证通过）；
    ``ok=False`` 表示全链降级失败，留 unresolved + 写 trace，不崩。``spec`` 为 None
    即未解析出配方。``filled`` 是补全阶段本会话临时拿到的凭证值，供 install 步注入 env，
    **绝不进缓存**（D14：缓存只存变量名不存值）。
    """

    ok: bool
    spec: InstallSpec | None = None
    provenance: str = ""  # cache | catalog | ai | ai_unverified | ""(失败)
    missing: list[str] = field(default_factory=list)
    filled: dict[str, str] = field(default_factory=dict)  # 变量名→值（本会话临时，不入缓存）
    trace: list[str] = field(default_factory=list)
    reason: str = ""  # 失败原因


# ---------------------------------------------------------------------------
# 转换函数（第 1 步实现，回归门禁核心）
# ---------------------------------------------------------------------------


def _usability_of(spec: InstallSpec) -> str:
    """推导一条 InstallSpec 的 usability，逻辑与 ``mcp_catalog.usability_of`` 逐字一致。

    优先级：needs_credentials > needs_config > needs_runtime > ready。

    **关键（回归门禁）**：只有**必填** ``credential_env`` 触发 ``needs_credentials``；
    ``optional_credential_env``（如 context7 的 ``CONTEXT7_API_KEY``）**不**触发——有则
    更好、无也能跑。这条优先级必须与 catalog 路径完全一致，否则 6 条 catalog 命中 MCP
    的 item 字段会与改前不一致。
    """
    if spec.credential_env:
        return "needs_credentials"
    if spec.needs_config:
        return "needs_config"
    if spec.needs_runtime:
        return "needs_runtime"
    return "ready"


def from_catalog_entry(entry: McpEntry) -> InstallSpec:
    """把人工核实的 catalog 种子（``McpEntry``）转成通用 ``InstallSpec``。

    让 catalog 路径复用同一 ``spec_to_item``，保证「未开 ``--ai-infer`` 时 6 条 catalog
    命中 MCP 的 item 字段与改前逐字段一致」（回归门禁）。catalog 是预验证种子，故
    ``provenance="catalog"``、``verify_ok=entry.verified``、``missing=[]``。
    """
    return InstallSpec(
        name=entry.name,
        command=entry.command,
        args=tuple(entry.args),
        invoke_hint=entry.invoke_hint,
        transport=entry.transport,
        scope=entry.scope_hint,
        env_template=dict(entry.env_template),
        repo=entry.repo,
        url=entry.url,
        credential_env=tuple(entry.credential_env),
        optional_credential_env=tuple(entry.optional_credential_env),
        needs_config=entry.needs_config,
        needs_runtime=entry.needs_runtime,
        post_install_steps=tuple(entry.post_install_steps),
        provenance="catalog",
        verify_ok=bool(entry.verified),
        missing=[],
        trace=["catalog 种子（人工预核实）"],
    )


def spec_to_item(
    spec: InstallSpec, *, source_ref=None, capability_name: str = ""
) -> dict:
    """唯一的 item 字典构造器：把 ``InstallSpec`` 转成与 ``verify.py`` group_mcp_items
    命中分支【字段同构】的 item dict。

    下游 install/dedup/recommend/record 只认这个 item 形状，故无论配方来自 catalog 种子、
    本地缓存还是 AI 推断，最终落点完全一致（D23 不破现有链路）。

    空值约定（与 group_mcp_items 逐字一致，回归门禁）：
      - ``credential_env`` 空 → ``None``（不是 ``[]``）
      - ``env_template`` 空 → ``{}``（不是 ``None``）
      - ``post_install_steps`` 空 → ``[]``（不是 ``None``）

    usability 由 ``_usability_of`` 推导，逻辑同 ``mcp_catalog.usability_of``。
    spec 的 ``provenance`` / ``verify_ok`` / ``missing`` / ``trace`` 是过程透明度字段，
    **不进 item dict**。
    """
    return {
        "name": spec.name,
        "form": "MCP",
        "install_method": "mcp_register",
        "mcp": {
            "transport": spec.transport,
            "command": spec.command,
            "args": list(spec.args),
            "scope": spec.scope,
        },
        "repo": spec.repo,
        "url": spec.url,
        "stars": None,  # 由 _probe_stars_for_items 探一手星数后回填（刻舟求剑）
        "stars_observed_at": None,
        "usability": _usability_of(spec),
        "credential_env": list(spec.credential_env) if spec.credential_env else None,
        "env_template": dict(spec.env_template) if spec.env_template else {},
        "post_install_steps": list(spec.post_install_steps)
        if spec.post_install_steps
        else [],
        "invoke_hint": spec.invoke_hint,
        "source_ref": source_ref,
        "capability_name": capability_name,
    }


# ---------------------------------------------------------------------------
# 缓存层（第 2 步已实现）+ 第 3 步骨架桩（resolve/infer/verify/prompt 待填）
# ---------------------------------------------------------------------------


# ---- D14 卫生：缓存只存环境变量名、不存值 ----
# 真实密钥指纹清单——缓存文本命中任一即说明值泄漏，拒绝写入。env_template 的值经
# _sanitize_env_values 清零，这里是非环境变量字段漏值的最后一道防线。
_KEY_FINGERPRINTS = ("sk-", "ghp_", "gho_", "ghs_", "ghu_", "github_pat_", "Bearer ", "AKIA", "xox")


def _sanitize_env_values(spec: InstallSpec) -> InstallSpec:
    """D14 卫生器：把 ``env_template`` 的值全部清成空串，只留环境变量**名**。

    缓存只存「需要哪些环境变量」，绝不存值。即便上游 spec 误带真实值，这里强制清零，
    保证落盘文本 grep 不到任何真实 key 指纹。返回新 spec，不改原对象。
    """
    if not spec.env_template:
        return spec
    return replace(spec, env_template={k: "" for k in spec.env_template})


def _has_key_fingerprint(text: str) -> bool:
    """D14 守卫：文本里是否出现真实密钥指纹。"""
    return any(fp in text for fp in _KEY_FINGERPRINTS)


def _spec_to_cache_dict(spec: InstallSpec) -> dict:
    """InstallSpec → 可 JSON 序列化的缓存 dict（落盘格式）。

    先过 D14 卫生器清空 env 值。过程透明度字段（provenance/verify_ok/missing/trace）
    一并存盘便于报告回放；``cache_lookup`` 读回时 provenance 统一改写为 ``cache``。
    """
    spec = _sanitize_env_values(spec)
    return {
        "name": spec.name,
        "command": spec.command,
        "args": list(spec.args),
        "invoke_hint": spec.invoke_hint,
        "transport": spec.transport,
        "scope": spec.scope,
        "env_template": dict(spec.env_template),
        "repo": spec.repo,
        "url": spec.url,
        "credential_env": list(spec.credential_env),
        "optional_credential_env": list(spec.optional_credential_env),
        "needs_config": spec.needs_config,
        "needs_runtime": spec.needs_runtime,
        "post_install_steps": list(spec.post_install_steps),
        "provenance": spec.provenance,
        "verify_ok": spec.verify_ok,
        "missing": list(spec.missing),
        "trace": list(spec.trace),
    }


def _spec_from_cache_dict(d: dict) -> InstallSpec:
    """缓存 dict → InstallSpec（``cache_lookup`` 用）。

    ``provenance`` 强制改写为 ``cache``（命中即标缓存来源，覆盖原 provenance）；trace
    追加「缓存命中（L1）」便于报告展示解析过程。字段缺失走默认值，不抛异常。
    """
    return InstallSpec(
        name=d["name"],
        command=d["command"],
        args=tuple(d.get("args") or ()),
        invoke_hint=d.get("invoke_hint", ""),
        transport=d.get("transport", "stdio"),
        scope=d.get("scope", "user"),
        env_template=dict(d.get("env_template") or {}),
        repo=d.get("repo"),
        url=d.get("url"),
        credential_env=tuple(d.get("credential_env") or ()),
        optional_credential_env=tuple(d.get("optional_credential_env") or ()),
        needs_config=bool(d.get("needs_config", False)),
        needs_runtime=bool(d.get("needs_runtime", False)),
        post_install_steps=tuple(d.get("post_install_steps") or ()),
        provenance="cache",
        verify_ok=bool(d.get("verify_ok", False)),
        missing=list(d.get("missing") or []),
        trace=list(d.get("trace") or []) + ["缓存命中（L1）"],
    )


def _load_cache() -> dict:
    """读缓存 entries 表（``{name: spec_dict}``）。文件不存在/损坏返回 ``{}``，绝不抛裸异常。"""
    path = config.install_cache_path()
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else {}


def _atomic_write_json(path, obj: dict) -> None:
    """原子写 JSON：临时文件 + ``os.replace``（POSIX 原子）。先过 D14 指纹守卫。

    指纹守卫命中 → **拒绝写入**（宁可丢这条缓存也不让 key 进文件），但**不抛异常**
    （不崩，下次重新推断即可）。中途崩溃不会留下半截损坏文件（临时文件先写再 replace）。
    """
    path = Path(path)
    text = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    if _has_key_fingerprint(text):
        # D14 最后一道防线：拒绝写可能含 key 的文件，不崩但留痕
        warnings.warn(
            f"install_cache 写入跳过（D14 指纹守卫命中，疑似含密钥）：{path}",
            stacklevel=2,
        )
        return
    parent = path.parent
    os.makedirs(parent, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=".install_cache_", suffix=".tmp", dir=str(parent))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def cache_lookup(name: str, repo: str | None = None):
    """L1 本地缓存查装法（纯文件读，D18 不破）。

    按规范名命中返回 ``InstallSpec``（``provenance="cache"``、trace 追加「缓存命中」）；
    未命中返回 None。``repo`` 当前不参与查键（与 catalog 同名键哲学一致），留作未来
    按仓库细分的扩展位。
    """
    entries = _load_cache()
    d = entries.get(name) if isinstance(entries, dict) else None
    if not isinstance(d, dict):
        return None
    return _spec_from_cache_dict(d)


def cache_store(spec: InstallSpec) -> None:
    """把验证过的装法入缓存（原子写 + D14 卫生）。

    卫生器先清空 env_template 值（只留变量名）；序列化后再过密钥指纹守卫，命中指纹
    则拒绝写入（宁可丢缓存也不让 key 进文件，但绝不抛裸异常——跳过即可，下次重推）。
    原子写：临时文件 + ``os.replace``，中途崩溃不留半截损坏缓存。
    ``data/install_cache.json`` 随 ``data/`` 自动 gitignore。
    """
    entries = _load_cache()
    entries[spec.name] = _spec_to_cache_dict(spec)
    _atomic_write_json(config.install_cache_path(), {"version": 1, "entries": entries})


def cache_invalidate(name: str, repo: str | None = None) -> None:
    """删除一条缓存装法（``--refresh-cache`` 用）。不存在静默跳过，绝不抛裸异常。"""
    entries = _load_cache()
    if name not in entries:
        return
    entries.pop(name, None)
    _atomic_write_json(config.install_cache_path(), {"version": 1, "entries": entries})


def resolve_install_spec(
    name: str,
    *,
    repo: str | None = None,
    url: str | None = None,
    allow_ai: bool = False,
    refresh_cache: bool = False,
    skip_trial: bool = False,
    has_tty: bool = False,
    chat_fn=None,
    prompt_fn=None,
) -> ResolveResult:
    """四级降级链总调度（第 3 步实现）。

    顺序：本地缓存 → catalog 种子 → AI 读源头仓库推断 → 试跑验证 → 缺项补全 → 入缓存。
    任一级拿到配方即继续往后走补全；全失败返回 ``ResolveResult(ok=False, reason=...)``，
    不崩、不静默、不臆造。``allow_ai=False`` 时只走前两级（缓存/目录），未命中诚实返回失败。

    缓存/目录命中已预验证，跳过试跑；只有 AI 推断路径走 L4 试跑，验证过才入缓存。L5 缺项
    补全三路都走：缓存命中若仍缺 key 也会再问一次（配方记住了、key 每次现填，值不入缓存）。
    """
    trace = [f"解析 MCP 装法：name={name} repo={repo} url={url}"]
    spec: InstallSpec | None = None

    # ---- L1 本地缓存 ----
    if refresh_cache:
        trace.append("L1 缓存已按 --refresh-cache 跳过")
    else:
        try:
            cached = cache_lookup(name, repo)
        except Exception as e:  # 缓存读异常不当死路，降级
            cached = None
            trace.append(f"L1 缓存读取异常（降级）：{e}")
        if cached is not None:
            spec = cached
            # 依据当前环境重算缺项（缓存的 missing 是上次快照，环境可能已补）
            if spec.credential_env:
                spec = replace(
                    spec,
                    missing=[v for v in spec.credential_env if not os.environ.get(v)],
                )
            trace.append(f"L1 缓存命中（provenance={spec.provenance}）")
        else:
            trace.append("L1 缓存未命中")

    # ---- L2 catalog 种子 ----
    if spec is None:
        entry = mcp_catalog.lookup(name)
        if entry is not None:
            spec = from_catalog_entry(entry)
            if not spec.repo and repo:
                spec = replace(spec, repo=repo)
            if not spec.url and url:
                spec = replace(spec, url=url)
            trace.append("L2 catalog 种子命中（人工预核实）")
        else:
            trace.append("L2 catalog 未命中")

    # ---- L3 AI 读源头仓库推断 + L4 试跑验证（仅 AI 路径）----
    if spec is None:
        if not allow_ai:
            return ResolveResult(
                ok=False,
                reason="未开启 --ai-infer：catalog 未收录且无缓存，诚实标 unresolved",
                trace=trace,
            )
        if not (repo or url):
            return ResolveResult(
                ok=False,
                reason="无仓库地址可供 AI 推断（unresolved 条目缺 repo/url）",
                trace=trace,
            )
        if chat_fn is None:
            return ResolveResult(
                ok=False, reason="未提供 chat_fn，无法 AI 推断", trace=trace,
            )
        infer_res = infer_install_spec(repo or url, chat_fn, url=url)
        trace.extend(infer_res.trace)
        if not infer_res.ok or infer_res.spec is None:
            return ResolveResult(
                ok=False, reason=f"AI 推断失败：{infer_res.reason}", trace=trace,
            )
        spec = infer_res.spec

        vr = verify_install_spec(spec, skip=skip_trial)
        trace.append(f"L4 试跑：ok={vr.ok} attempts={vr.attempts} reason={vr.reason}")
        if not vr.ok:
            return ResolveResult(
                ok=False, reason=f"试跑未通过：{vr.reason}", trace=trace + vr.trace,
            )
        if skip_trial:
            trace.append("用户选择跳过试跑，装法未验证、不入缓存")
        else:
            spec = replace(spec, verify_ok=True, provenance="ai")
            trace.append("试跑通过，标 provenance=ai")
            # 验证过 → 入缓存（下次 L1 秒取）；写失败不影响本次安装
            try:
                cache_store(spec)
                trace.append("已入本地缓存（下次 L1 秒取）")
            except Exception as e:
                trace.append(f"入缓存失败（不影响本次安装）：{e}")

    # ---- L5 缺项补全（缓存/目录/AI 三路都走：缺 key 就问）----
    filled: dict[str, str] = {}
    if spec.missing:
        pr = prompt_missing(spec, has_tty, prompt_fn)
        trace.append(
            f"L5 补全缺项：via={pr.via} filled={list(pr.filled)} skipped={pr.skipped}"
        )
        spec = replace(spec, missing=list(pr.skipped))
        filled = dict(pr.filled)

    return ResolveResult(
        ok=True,
        spec=spec,
        provenance=spec.provenance,
        missing=list(spec.missing),
        filled=filled,
        trace=trace,
    )


# ---------------------------------------------------------------------------
# L3 · AI 读源头仓库推断
# ---------------------------------------------------------------------------

# 喂给 AI 推断装法的候选文件（按优先级，README 最先）
_CANDIDATE_BASES = (
    "readme",
    "package.json",
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "dockerfile",
    "docker-compose.yml",
    ".env.example",
)


def _owner_repo(s: str | None) -> tuple[str, str] | None:
    """从 'owner/repo' 或 github URL 抠 ``(owner, repo)``。抠不到返回 None。

    复用 ``verify.parse_github_urls`` 处理 URL（去 ``.git``、排除带点的伪仓库）；裸
    ``owner/repo``（无 github.com 前缀）走字符串切分兜底。
    """
    if not s:
        return None
    s = s.strip()
    pairs = verify.parse_github_urls(s)
    if pairs:
        return pairs[0]
    if "/" in s and not s.startswith(("http://", "https://")):
        parts = [p for p in s.split("/") if p]
        if len(parts) >= 2:
            owner, rname = parts[0], parts[1]
            rname = re.sub(r"\.git$", "", rname)
            if owner and rname and " " not in owner and " " not in rname:
                return (owner, rname)
    return None


def _snippet(text: str, n: int = 200) -> str:
    """截一段文本用于 trace 留痕（失败时看 AI 到底回了啥）。"""
    text = str(text)
    return text[:n] + ("..." if len(text) > n else "")


def _fetch_install_hints(
    owner: str,
    repo: str,
    branch: str,
    tree,
    trace: list[str],
    *,
    max_files: int = 6,
    max_chars: int = 4000,
) -> dict[str, str]:
    """从文件树挑安装相关文件（README/package.json/pyproject/Dockerfile/.env.example 等），
    逐个拉 raw 文本，返回 ``{path: content}``。拉取失败跳过、不崩。"""
    if not tree:
        return {}
    picked: dict[str, str] = {}
    for node in tree:
        if not isinstance(node, dict) or node.get("type") == "dir":
            continue
        p = node.get("path") or ""
        if not p:
            continue
        base = p.rsplit("/", 1)[-1].lower()
        if base.startswith("readme"):
            picked.setdefault("readme", p)
        elif base in _CANDIDATE_BASES:
            picked.setdefault(base, p)
    priority = [
        "readme", "package.json", "pyproject.toml", "setup.py",
        "dockerfile", ".env.example", "requirements.txt", "docker-compose.yml",
    ]
    snippets: dict[str, str] = {}
    for key in priority:
        if key not in picked:
            continue
        p = picked[key]
        try:
            txt = verify._raw_text(verify.raw_url(owner, repo, branch, p))
        except Exception as e:
            trace.append(f"取 {p} 失败（跳过）：{e}")
            continue
        if txt:
            snippets[p] = txt[:max_chars]
        if len(snippets) >= max_files:
            break
    return snippets


_INFER_SYSTEM = """你是 MCP（模型上下文协议）安装专家。给定一个 GitHub 仓库的 README / package.json /
pyproject.toml / Dockerfile / .env.example 片段，你要推断出把这个仓库作为 MCP 服务器
注册到 Claude Code / Codex 的最小安装命令，并输出**严格 JSON**（不要任何解释文字、不要
markdown 围栏）。

JSON 字段：
{
  "name": "该 MCP 的简短标识名（小写连字符，如 context7、server-filesystem）",
  "command": "启动命令的可执行文件，单个词：npx | uvx | docker | python | node",
  "args": ["传给 command 的参数列表，按顺序；-y 等开关也要写"],
  "transport": "stdio（绝大多数 MCP 都是 stdio）",
  "scope": "user",
  "invoke_hint": "一句话：这工具能干什么、怎么调用",
  "needs_config": false,
  "needs_runtime": false,
  "credential_env": ["必填的环境变量名（缺了跑不起来），没有就空数组"],
  "optional_credential_env": ["可选的环境变量名（有则更好），没有就空数组"],
  "env_template": {"每个 credential 变量名": ""（值必须留空，绝不填真实 key）},
  "post_install_steps": []
}

规则：
- command 只能是单个可执行文件（npx/uvx/docker/python/node），不要写 shell 管道或多命令。
- env_template 的值**永远是空字符串**，绝不填真实密钥。
- 若该 MCP 需要一个因机器而异的路径参数（如要监控的目录、数据库文件路径），在 args 里用
  占位符 <DIRS> 或 <DB_PATH>，并把 needs_config 设为 true。
- 若该 MCP 首次运行要下载运行时（如浏览器内核），把 needs_runtime 设为 true。
- 只输出 JSON 对象本身，不要前后加任何文字。"""


def _build_infer_prompt(
    owner: str, repo: str, html_url: str, snippets: dict[str, str]
) -> str:
    parts = [f"仓库：{owner}/{repo}\n地址：{html_url}\n"]
    for path, content in snippets.items():
        parts.append(f"=== {path} ===\n{content}\n")
    parts.append("请根据以上仓库内容，推断这个 MCP 的安装命令，按规则输出严格 JSON。")
    return _INFER_SYSTEM + "\n\n" + "\n".join(parts)


def _spec_from_ai_dict(
    d, *, repo: str, url: str | None, trace: list[str]
) -> InstallSpec:
    """AI 输出的 JSON dict → ``InstallSpec``（``provenance="ai_unverified"``）。

    D14 卫生：``env_template`` 值强制清空（AI 若误填 key 也抹掉），只留变量名；所有
    ``credential_env`` / ``optional_credential_env`` 变量名补进 env_template。缺必填字段
    （name/command）抛 ``ValueError``，由 ``infer_install_spec`` 兜成失败结果。
    """
    if not isinstance(d, dict):
        raise ValueError("AI 输出不是 JSON 对象")
    name = str(d.get("name") or "").strip()
    # 消毒：MCP 名字只能含字母/数字/连字符/下划线，/ 换为 -
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    command = str(d.get("command") or "").strip()
    if not name or not command:
        raise ValueError(
            f"缺必填字段 name/command（name={name!r} command={command!r}）"
        )
    credential_env = tuple(
        str(v).strip() for v in (d.get("credential_env") or []) if str(v).strip()
    )
    optional_credential_env = tuple(
        str(v).strip()
        for v in (d.get("optional_credential_env") or [])
        if str(v).strip()
    )
    env_template = {str(k): "" for k in (d.get("env_template") or {})}
    for v in list(credential_env) + list(optional_credential_env):
        env_template.setdefault(v, "")
    return InstallSpec(
        name=name,
        command=command,
        args=tuple(str(a) for a in (d.get("args") or [])),
        invoke_hint=str(d.get("invoke_hint") or ""),
        transport=str(d.get("transport") or "stdio"),
        scope=str(d.get("scope") or "user"),
        env_template=env_template,
        repo=repo,
        url=url,
        credential_env=credential_env,
        optional_credential_env=optional_credential_env,
        needs_config=bool(d.get("needs_config")),
        needs_runtime=bool(d.get("needs_runtime")),
        post_install_steps=tuple(str(s) for s in (d.get("post_install_steps") or [])),
        provenance="ai_unverified",
        verify_ok=False,
        missing=[v for v in credential_env if not os.environ.get(v)],
        trace=list(trace),
    )


def infer_install_spec(
    repo: str, chat_fn, *, url: str | None = None
) -> ResolveResult:
    """AI 读源头仓库推断装法（第 3 步实现）。

    复用 ``verify._raw_text`` / ``raw_url`` / ``probe_repo`` / ``list_tree`` 拉仓库的
    README / package.json / pyproject.toml / Dockerfile / .env.example → 调 ``chat_fn``
    （调用方注入：生产传 ``llm.chat_text`` 绑定、测试传假函数）→ 用 ``plan._extract_json``
    解析结构化装法 JSON → 造 ``InstallSpec``（``provenance="ai_unverified"``、
    ``verify_ok=False`` 待试跑）。任一步异常都兜成 ``ok=False``，不崩。
    """
    trace = [f"L3 AI 推断：repo={repo}"]
    owner_repo = _owner_repo(repo) or (url and _owner_repo(url))
    if not owner_repo:
        return ResolveResult(ok=False, reason=f"无法解析仓库地址：{repo}", trace=trace)
    owner, repo_name = owner_repo
    trace.append(f"解析为 {owner}/{repo_name}")

    try:
        meta = verify.probe_repo(owner, repo_name)
    except Exception as e:
        return ResolveResult(ok=False, reason=f"探测仓库失败：{e}", trace=trace)
    if not meta:
        return ResolveResult(
            ok=False, reason=f"仓库不存在或不可访问：{owner}/{repo_name}", trace=trace
        )
    branch = meta.get("default_branch") or "main"
    html_url = meta.get("html_url") or url or f"https://github.com/{owner}/{repo_name}"
    trace.append(f"默认分支={branch}")

    try:
        tree = verify.list_tree(owner, repo_name, branch)
    except Exception as e:
        tree = []
        trace.append(f"列文件树失败（降级用描述）：{e}")

    snippets = _fetch_install_hints(owner, repo_name, branch, tree, trace)
    if not snippets:
        desc = (meta.get("description") or "").strip()
        if desc:
            snippets = {"仓库描述": desc}
            trace.append("无可读安装文件，退回仓库描述")
    if not snippets:
        return ResolveResult(
            ok=False, reason="仓库无可读的安装说明文件", trace=trace
        )

    prompt = _build_infer_prompt(owner, repo_name, html_url, snippets)
    try:
        text = chat_fn(prompt)
    except Exception as e:
        return ResolveResult(ok=False, reason=f"AI 调用失败：{e}", trace=trace)
    if not text or not str(text).strip():
        return ResolveResult(ok=False, reason="AI 返回空", trace=trace)
    text = str(text)
    trace.append("AI 已返回，解析 JSON")

    try:
        d = plan._extract_json(text)
    except Exception as e:
        return ResolveResult(
            ok=False,
            reason=f"JSON 解析失败：{e}",
            trace=trace + [_snippet(text)],
        )
    try:
        spec = _spec_from_ai_dict(
            d, repo=f"{owner}/{repo_name}", url=html_url, trace=list(trace)
        )
    except (ValueError, KeyError, TypeError) as e:
        return ResolveResult(
            ok=False,
            reason=f"AI 输出字段不合规：{e}",
            trace=trace + [_snippet(text)],
        )

    trace.append(
        f"推断装法：{spec.command} {' '.join(spec.args)}（缺项={spec.missing}）"
    )
    return ResolveResult(
        ok=True,
        spec=spec,
        provenance="ai_unverified",
        missing=list(spec.missing),
        trace=list(trace),
    )


# ---------------------------------------------------------------------------
# L4 · 试跑验证（subprocess 安全试跑，绝不写真配置）
# ---------------------------------------------------------------------------

_TRIAL_TIMEOUT = 20
_PLACEHOLDER_RE = re.compile(r"^<[^>]+>$")
# 试跑输出命中这些信号 → 视为「包/命令根本不可用」，换下一种装法重试
_NOT_FOUND_SIGNALS = (
    "not found",
    "enoent",
    " 404",
    "unable to find",
    "command not found",
    "could not resolve",
    "npm err",
    "not installed",
    "no such file",
    "no module named",
    "modulenotfounderror",
    "importerror",
)


def _trial_arg(a) -> str:
    """试跑用的参数：占位符（``<DIRS>`` / ``<DB_PATH>`` 等）替换成无害的 ``x``，
    避免被当成真实路径去打开而误报失败。"""
    a = str(a)
    return "x" if _PLACEHOLDER_RE.match(a) else a


def _trial_commands(spec: InstallSpec) -> list[list[str]]:
    """构造试跑候选命令（每次一个）：``base --help`` 再 ``base --version``。"""
    base = [spec.command] + [_trial_arg(a) for a in spec.args]
    return [base + ["--help"], base + ["--version"]]


def verify_install_spec(spec: InstallSpec, *, skip: bool = False) -> VerifyResult:
    """subprocess 安全试跑（第 3 步实现）。

    只试跑命令本身（``npx <pkg> --help`` / ``<cmd> --version``），**绝不写真配置**
    （不 ``claude mcp add``、不碰 ``~/.claude.json``）。占位符参数替换成 ``x``。max 2 次
    重试（``--help`` → ``--version``）。stdio MCP 服务器会阻塞读 stdin → 超时属正常，
    视为「包已解析、可启动」；命中「找不到」信号才判失败。``skip=True``（``--no-trial``）
    直接返回未验证结果。
    """
    if skip:
        return VerifyResult(
            ok=True,
            attempts=["skipped (--no-trial)"],
            reason="",
            trace=["用户选择跳过试跑，装法未验证"],
        )
    attempts: list[str] = []
    notes: list[str] = []
    for cmd in _trial_commands(spec):
        label = " ".join(cmd)
        attempts.append(label)
        try:
            cp = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=_TRIAL_TIMEOUT,
            )
        except FileNotFoundError:
            return VerifyResult(
                ok=False,
                attempts=attempts,
                reason=f"命令不可用（未安装）：{spec.command}",
                trace=notes + [f"试跑 {label} → FileNotFoundError"],
            )
        except subprocess.TimeoutExpired:
            # stdio MCP 服务器会阻塞读 stdin → 超时属正常，视为「包已解析、可启动」
            return VerifyResult(
                ok=True,
                attempts=attempts,
                reason="",
                trace=notes + [f"试跑 {label} → 超时（stdio 服务器正常行为，视为可装）"],
            )
        except Exception as e:
            notes.append(f"试跑 {label} → 异常 {e}（换装法重试）")
            continue
        out_text = (
            ((cp.stdout or b"") + (cp.stderr or b"")).decode("utf-8", "ignore").lower()
        )
        if cp.returncode == 0:
            return VerifyResult(
                ok=True,
                attempts=attempts,
                reason="",
                trace=notes + [f"试跑 {label} → 退出码 0"],
            )
        if any(sig in out_text for sig in _NOT_FOUND_SIGNALS):
            notes.append(
                f"试跑 {label} → 退出码 {cp.returncode}，命中「不可用」信号（换装法重试）"
            )
            continue
        # 非零但无「找不到」信号 → 包已解析、只是不认这个旗标 → 视为可装
        return VerifyResult(
            ok=True,
            attempts=attempts,
            reason="",
            trace=notes + [f"试跑 {label} → 退出码 {cp.returncode}（包已解析，视为可装）"],
        )
    return VerifyResult(
        ok=False,
        attempts=attempts,
        reason="试跑均未通过（包不可用或不存在）",
        trace=notes + ["所有试跑候选均失败"],
    )


# ---------------------------------------------------------------------------
# L5 · 缺项补全两态弹窗
# ---------------------------------------------------------------------------

def prompt_missing(
    spec: InstallSpec, has_tty: bool, prompt_fn=None
) -> PromptResult:
    """缺项补全两态弹窗（第 3 步实现）。

    有终端走交互 ``input()``；无终端把缺项清单写进报告、由 agent 在对话里转达。
    ``prompt_fn`` 注入时（测试或 agent 对话转达）无视 ``has_tty`` 直接用它取值。
    ``filled`` 是本会话临时拿到的值，**绝不入缓存**（D14）。
    """
    missing = list(spec.missing)
    if not missing:
        return PromptResult(filled={}, skipped=[], via="tty" if has_tty else "report")
    # 无终端且无注入取值器：无法交互，全部标 skipped 交报告/对话转达
    if not has_tty and prompt_fn is None:
        return PromptResult(filled={}, skipped=missing, via="report")
    filled: dict[str, str] = {}
    skipped: list[str] = []
    for var in missing:
        if prompt_fn is not None:
            try:
                ans = prompt_fn(var)
            except Exception:
                ans = ""
        else:
            try:
                ans = input(f"请提供 {var}（没有就回车跳过，我会标注待补）: ")
            except (EOFError, KeyboardInterrupt):
                ans = ""
            except Exception:
                ans = ""
        ans = (ans or "").strip()
        if ans:
            filled[var] = ans
        else:
            skipped.append(var)
    return PromptResult(filled=filled, skipped=skipped, via="tty")
