"""skillbrew 日志配置（包内私有，下划线开头）。

用法：CLI 入口（``skillbrew/cli/__init__.py`` 的 ``main()``）在解析参数前
调一次 ``_setup_logging()``，库代码不调 basicConfig。库代码获取 logger 统一用
``logging.getLogger(__name__)``，不要自己创建 handler。

- 默认 INFO：用户能看到阶段进度（``[i/n] 探仓库 ...`` 这类走 stderr）。
- ``LOGLEVEL=DEBUG`` 环境变量开详：包含 HTTP/缓存/重试等诊断。
- 产品输出（表格/结果/给用户看的引导/报错）继续用 ``print()``：
  - 正常结果走 stdout，方便 ``| jq``/``> report.md`` 管道；
  - CLI 报错（``[FAIL]``/hint）走 stderr，与日志流合流但仍是 print（多行
    人工格式化提示保持可读性，不 logger 化）。
- spinner/_print_progress 保留原 stderr 行覆盖动画（见 ``cli/utils.py``），
  不 logger 化。

零新依赖：只用 stdlib ``logging``。
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def _setup_logging() -> None:
    """初始化 root logger；只调一次，幂等。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = logging.DEBUG if os.environ.get("LOGLEVEL", "").upper() == "DEBUG" else logging.INFO
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(levelname)s %(message)s",
    )
    # 别让第三方库（urllib3/huggingface_hub 等）DEBUG 噪音污染 stderr
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.WARNING)
    logging.getLogger("faster_whisper").setLevel(logging.WARNING)
    _CONFIGURED = True
