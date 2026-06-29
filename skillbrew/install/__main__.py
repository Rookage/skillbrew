"""支持 python -m skillbrew.install 入口。"""

from __future__ import annotations

import sys

from .executor import _main

if __name__ == "__main__":
    sys.exit(_main())
