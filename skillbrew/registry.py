"""能力台账 Registry —— 所有已安装 AI 能力的结构化登记表。

去重 / 归并 / 分类 / 查询 / 移除（章程第 8 节）。存储用 SQLite（轻、单文件、可查）。
每装一个能力（Skill / MCP / 代码 / 配置）登记一行；被整并的标 status=merged。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

# data/registry.db 与本模块（skillbrew/skillbrew/registry.py）的相对位置：
#   registry.py -> parents[0]=skillbrew/skillbrew  parents[1]=skillbrew(项目根)
DB_PATH = Path(__file__).resolve().parents[1] / "data" / "registry.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS skills (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT UNIQUE NOT NULL,        -- skill 目录名（去重主键）
    display_name  TEXT,                        -- frontmatter 里的 name 字段
    category      TEXT,                        -- 分类：engineering / productivity / pre-existing ...
    form          TEXT,                        -- 形态：Skill / MCP / 代码 / 配置
    source        TEXT,                        -- 来源仓库，如 mattpocock/skills；本机已有=pre-existing
    source_video  TEXT,                        -- 原始素材 BV 号
    install_path  TEXT,                        -- 落地路径
    file_count    INTEGER,                     -- 该 skill 目录下文件数
    status        TEXT DEFAULT 'active',       -- active / merged / deprecated / skipped
    merged_into   TEXT,                        -- 若 merged，并入哪个 skill
    dedup_note    TEXT,                        -- 去重 / 整并说明
    attribution   TEXT,                        -- 原作者 + 许可证（开源合规）
    installed_at  TEXT,                        -- 登记时间（ISO）
    notes         TEXT
);

CREATE TABLE IF NOT EXISTS install_sessions (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT,                 -- 本次安装会话标识
    source_video         TEXT,
    authorization_choice TEXT,                 -- A / B / C / D / E
    skills_before        INTEGER,              -- 安装前 distinct skill 数
    skills_added         INTEGER,              -- 净新增
    skills_merged        INTEGER,              -- 整并数
    skills_after         INTEGER,              -- 安装后 distinct skill 数
    installed_at         TEXT,
    notes                TEXT
);
"""


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """连/建台账库，返回 row_factory=Row 的连接。"""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert_skill(conn: sqlite3.Connection, name: str, **fields: Any) -> None:
    """插入或更新一条 skill 记录（按 name 去重）。"""
    cols = ["name"] + list(fields.keys())
    vals = [name] + list(fields.values())
    placeholders = ",".join("?" * len(cols))
    update_cols = [c for c in fields if c != "name"]
    update_clause = (
        ",".join(f"{c}=excluded.{c}" for c in update_cols) if update_cols else "name=name"
    )
    sql = (
        f"INSERT INTO skills ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT(name) DO UPDATE SET {update_clause}"
    )
    conn.execute(sql, vals)
    conn.commit()


def record_session(conn: sqlite3.Connection, **fields: Any) -> None:
    """记一条安装会话（before/added/merged/after）。"""
    cols = list(fields.keys())
    vals = list(fields.values())
    placeholders = ",".join("?" * len(cols))
    conn.execute(
        f"INSERT INTO install_sessions ({','.join(cols)}) VALUES ({placeholders})", vals
    )
    conn.commit()


def list_skills(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM skills"
    params: tuple = ()
    if status:
        sql += " WHERE status=?"
        params = (status,)
    sql += " ORDER BY source, name"
    return [dict(r) for r in conn.execute(sql, params)]


def count_by_status(conn: sqlite3.Connection) -> dict:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM skills GROUP BY status")
    return {r["status"]: r["n"] for r in rows}


def remove_skill(conn: sqlite3.Connection, name: str) -> int:
    """从台账移除一条（可移除，章程 D7）。返回删除行数。"""
    cur = conn.execute("DELETE FROM skills WHERE name=?", (name,))
    conn.commit()
    return cur.rowcount


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
