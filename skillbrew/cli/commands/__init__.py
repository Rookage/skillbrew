"""CLI 子命令导出。"""

from __future__ import annotations

from .add import cmd_add
from .config import cmd_config
from .dedup import cmd_dedup
from .doctor import cmd_doctor
from .ingest import cmd_ingest
from .install import cmd_install
from .market import cmd_info, cmd_search
from .plan import cmd_plan
from .recommend import cmd_recommend
from .record import cmd_record
from .run import cmd_run
from .understand import cmd_understand
from .verify import cmd_verify

__all__ = [
    "cmd_add",
    "cmd_config",
    "cmd_dedup",
    "cmd_doctor",
    "cmd_info",
    "cmd_ingest",
    "cmd_install",
    "cmd_plan",
    "cmd_recommend",
    "cmd_record",
    "cmd_run",
    "cmd_search",
    "cmd_understand",
    "cmd_verify",
]
