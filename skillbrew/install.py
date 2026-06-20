"""install：安装 —— 照 dedup 判定的 new 技能，整目录从 GitHub raw 拷到本地 .claude/skills/，登记进台账。

刹车（章程 D18/刹车设计）：install 默认 dry-run——只列要装什么、不下载、不写台账；
带 --approve 才真落盘 + 写台账，保"你落盘就是什么"。

装哪些：
  - dedup 判 new 的 → 装（整目录拷：每个 skill = 其目录下全部文件）
  - dedup 判 merge 的 → 不自动装（整并需人工确认，标出来留给后面）
  - dedup 判 skip 的 → 不装（已装/已整并）
  - new 里 category=deprecated 的 → 默认跳过（--include-deprecated 才装）

纯 GitHub raw 下载（raw 不耗 API 限额）+ 标准库；不调 LLM、不耗 DeepSeek/Agnes 配额。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

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


def install(
    source_dir: Path, *, target_dir: Path | str | None = None,
    db_path: Path | str | None = None, approve: bool = False,
    include_deprecated: bool = False, on_progress=None,
) -> dict:
    """对一个源目录跑安装：读 install_list.json + dedup.json → 挑 new 整目录拷 → 登记台账。

    approve=False（默认）= dry-run，只返回计划（to_install/skipped_*），不下载不写台账。
    approve=True = 真下载每个文件到 target_dir/<name>/ + upsert 台账 + 记安装会话。
    返回报告 dict。纯 GitHub raw + 标准库，不调 LLM。
    target_dir 默认 ~/.claude/skills。
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

    by_name = {s["name"]: s for s in install_list.get("skills", [])}  # 回查 files/raw_url/dir_path

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

    plan = {
        "source_video": source_video,
        "verified_repo": full_name,
        "approve": approve,
        "target_dir": str(target),
        "before": before,
        "to_install": [d["name"] for d in to_install],
        "skipped_merge": [d["name"] for d in skipped_merge],
        "skipped_deprecated": [d["name"] for d in skipped_deprecated],
        "skipped_already": [d["name"] for d in skipped_already],
    }

    if not approve:
        plan["note"] = "dry-run：未下载、未写台账。加 --approve 才真装。"
        return plan

    # ---- 真装：整目录拷 + 登记 ----
    target.mkdir(parents=True, exist_ok=True)
    # db_path 默认 None → 用 registry 自己的 DB_PATH（别把 None 传进去盖掉默认值）
    conn = registry.connect(db_path if db_path is not None else registry.DB_PATH)
    installed: list[dict] = []
    try:
        total = len(to_install)
        for i, d in enumerate(to_install):
            name = d["name"]
            s = by_name[name]
            dest_dir = target / name
            if on_progress:
                on_progress(s, i, total)
            dest_dir.mkdir(parents=True, exist_ok=True)
            n_files = 0
            display_name = name
            for f in s.get("files", []):
                rel = _rel_within(s["dir_path"], f["path"])
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
                category=s.get("category", ""),
                form="Skill",
                source=full_name,
                source_video=source_video,
                install_path=str(dest_dir),
                file_count=n_files,
                status="active",
                attribution=f"{full_name}（GitHub 开源）",
                dedup_note="dedup 判定 new，整目录拷贝安装",
                installed_at=_now_iso(),
            )
            installed.append({
                "name": name, "display_name": display_name,
                "file_count": n_files, "path": str(dest_dir),
            })

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
                f"装 {len(installed)} 个新 skill；跳过 merge {len(skipped_merge)}/"
                f"deprecated {len(skipped_deprecated)}/已装 {len(skipped_already)}"
            ),
        )
    finally:
        conn.close()

    plan["installed"] = installed
    plan["after"] = after
    plan["note"] = f"已落盘 {len(installed)} 个 skill 到 {target}，并登记进台账。"
    return plan


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
    print(f"[OK] 装 {len(r['to_install'])} 个：{r['to_install']}")
    if not approve:
        print("     dry-run，未落盘。加 --approve 真装。")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
