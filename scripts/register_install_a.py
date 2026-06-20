"""登记 install A（装核心 16 个 Matt Pocock skill）到能力台账。

跑法（项目根 ai-self-evolution/skillbrew/ 下）：
    python scripts/register_install_a.py

做五件事：
  ① 建/连 data/registry.db；
  ② 扫工作区已装 skill，凡非本次新增的登记为 pre-existing baseline；
  ③ 登记本次新增 15 个 Matt skill（source=mattpocock/skills）+ 1 个 tdd 整并（merged）；
  ④ 记一条 install_sessions（before/added/merged/after）；
  ⑤ 打印台账摘要。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # ai-self-evolution/skillbrew/
sys.path.insert(0, str(ROOT))

from skillbrew.registry import (  # noqa: E402
    connect,
    count_by_status,
    list_skills,
    now_iso,
    record_session,
    upsert_skill,
)

WORKSPACE_SKILLS = Path(
    "./.claude/skills"
)

# 本次 install A 新增的 15 个 Matt skill（目录名）；tdd 是整并不算新增目录
MATT_NEW = {
    "productivity-grill-me", "productivity-grilling", "productivity-handoff",
    "productivity-teach", "productivity-writing-great-skills",
    "engineering-grill-with-docs", "engineering-domain-modeling",
    "engineering-diagnosing-bugs", "engineering-codebase-design",
    "engineering-implement", "engineering-prototype", "engineering-triage",
    "engineering-to-issues", "engineering-to-prd", "engineering-resolving-merge-conflicts",
}

SOURCE = "mattpocock/skills"
VIDEO = "BV1UpR9BBEf5"
ATTR = "Matt Pocock · MIT License · github.com/mattpocock/skills"
TS = now_iso()


def _file_count(d: Path) -> int:
    return sum(1 for _ in d.rglob("*") if _.is_file())


def main() -> None:
    conn = connect()

    # ① baseline：工作区全部 skill 目录，凡不在 MATT_NEW 的都算本机已有
    all_dirs = sorted(d.name for d in WORKSPACE_SKILLS.iterdir() if d.is_dir())
    baseline = [d for d in all_dirs if d not in MATT_NEW]
    for name in baseline:
        d = WORKSPACE_SKILLS / name
        upsert_skill(
            conn, name,
            category="pre-existing", form="Skill", source="pre-existing",
            install_path=str(d), file_count=_file_count(d), status="active",
            attribution="本机已装（非本次安装）", installed_at=TS,
            notes="baseline 扫描登记",
        )

    # ② 本次新增 15 个
    for name in sorted(MATT_NEW):
        d = WORKSPACE_SKILLS / name
        cat = "productivity" if name.startswith("productivity-") else "engineering"
        upsert_skill(
            conn, name,
            category=cat, form="Skill", source=SOURCE, source_video=VIDEO,
            install_path=str(d), file_count=_file_count(d), status="active",
            attribution=ATTR, installed_at=TS,
        )

    # ③ tdd 整并：方法论并入 Python测试技能，不新增独立 skill
    upsert_skill(
        conn, "tdd",
        display_name="tdd", category="engineering", form="Skill",
        source=SOURCE, source_video=VIDEO,
        install_path=str(WORKSPACE_SKILLS / "Python测试技能"),
        file_count=4, status="merged", merged_into="Python测试技能",
        dedup_note="方法论（垂直切片/tracer bullet/好测试即spec）整并进 Python测试技能，红绿重构不重复",
        attribution=ATTR, installed_at=TS,
        notes="四文件（tdd-methodology.md/tests.md/mocking.md/refactoring.md）作为 Python测试技能 伴随文件",
    )

    # ④ 会话记录
    before = len(baseline)   # 25
    added = len(MATT_NEW)    # 15
    merged = 1               # tdd
    after = before + added   # 40
    record_session(
        conn,
        session_id=f"install-a-{TS}",
        source_video=VIDEO, authorization_choice="A",
        skills_before=before, skills_added=added,
        skills_merged=merged, skills_after=after,
        installed_at=TS,
        notes="核心 16 个：15 净新增 + tdd 整并进 Python测试技能",
    )

    # ⑤ 摘要
    print("===== 能力台账摘要 =====")
    print("按状态计数：", count_by_status(conn))
    print(f"baseline(pre-existing)={before}  新增={added}  整并={merged}  after={after}")
    print("按来源计数：")
    for r in conn.execute("SELECT source, COUNT(*) n FROM skills GROUP BY source ORDER BY source"):
        print(f"  {r['source']}: {r['n']}")
    print("\n本次 install A 登记项：")
    for s in list_skills(conn):
        if s["source"] == SOURCE:
            tag = f"[merged→{s['merged_into']}]" if s["status"] == "merged" else "[active]"
            print(f"  {tag} {s['name']}  ({s['category']}, {s['file_count']}文件)")

    conn.close()
    print("\n✅ 台账登记完成：", ROOT / "data" / "registry.db")


if __name__ == "__main__":
    main()
