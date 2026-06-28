"""ratelimit：GitHub REST API 客户端主动令牌桶限流。

GitHub 匿名访问限额：
  - search 桶（/search/... 端点）：10 req / min
  - core 桶（其他 api.github.com 端点）：60 req / hr
  - raw.githubusercontent.com：不占用 API 限额，不管控

策略：
  1. 发请求前 acquire_for_url(url) 按桶取令牌（不够就 sleep 等）；
  2. 收到响应后 update_from_headers(url, headers) 用服务器返回的
     X-RateLimit-Remaining/Reset/Resource 头同步本地桶状态，避免估算漂移。
  3. 即便本地桶估计充足仍撞 403（例如别处进程也在消耗），verify._api_json
     会 fallback 到 gh CLI，本模块不拦——本模块只做"尽量不撞"，不做最终兜底。

线程安全：TokenBucket 自带 threading.Lock，installer/vision 的线程池里并发调用也安全。
可测性：构造时可注入 time_func / sleep_func，测试不用真睡。
"""

from __future__ import annotations

import threading
import time
import urllib.parse
import warnings
from collections.abc import Callable

_API_HOST = "api.github.com"
_SEARCH_PREFIX = "/search/"

# 速率常量（匿名访问）
_SEARCH_RATE = 10.0 / 60.0  # 每秒补 10/60 个令牌（= 10 个/分）
_SEARCH_CAPACITY = 10
_CORE_RATE = 60.0 / 3600.0  # 每秒补 60/3600 个令牌（= 60 个/时）
_CORE_CAPACITY = 60


class TokenBucket:
    """经典令牌桶：rate 个/秒补充，最多 capacity 个，acquire 时若不够就阻塞等。"""

    def __init__(
        self,
        rate: float,
        capacity: float,
        *,
        time_func: Callable[[], float] | None = None,
        sleep_func: Callable[[float], None] | None = None,
    ) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._time = time_func or time.monotonic
        self._sleep = sleep_func or time.sleep
        self._last = self._time()
        self._lock = threading.Lock()

    # --- 内部：不加锁版，调用方必须持锁 ---
    def _refill_unlocked(self) -> None:
        now = self._time()
        elapsed = now - self._last
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last = now

    # --- 外部接口 ---
    def acquire(self, tokens: float = 1.0) -> None:
        """阻塞直到拿到 tokens 个令牌。"""
        while True:
            with self._lock:
                self._refill_unlocked()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                # 需要等多久才凑够
                need = tokens - self._tokens
                wait = need / self._rate if self._rate > 0 else float("inf")
            # 锁外 sleep，不阻塞其他线程 refill 观察
            if wait > 0:
                self._sleep(wait)

    def remaining(self) -> float:
        """当前瞬时剩余令牌数（调试/测试用，下一刻就可能变）。"""
        with self._lock:
            self._refill_unlocked()
            return self._tokens

    def set_remaining(self, n: float) -> None:
        """用服务器权威值覆盖本地估算（X-RateLimit-Remaining）。"""
        with self._lock:
            self._refill_unlocked()
            # 取 min：服务器说没剩就一定没剩；服务器说剩很多但本地估算更少，以服务器为准
            self._tokens = max(0.0, min(self._capacity, float(n)))
            self._last = self._time()

    def reset_at(self, unix_ts: float) -> None:
        """可选：服务器给的 X-RateLimit-Reset（Unix 秒），本实现不强制用——
        我们的 refill 是平滑补的，不用等整分钟/整小时 reset。
        留接口以便将来想精确同步 reset 点时扩展。"""


# --- 模块级两个单例 ---
_search_bucket = TokenBucket(_SEARCH_RATE, _SEARCH_CAPACITY)
_core_bucket = TokenBucket(_CORE_RATE, _CORE_CAPACITY)


def _reset_buckets_for_tests() -> None:
    """测试专用：把两个桶重置到满桶状态，避免测试间状态串扰。"""
    global _search_bucket, _core_bucket
    _search_bucket = TokenBucket(_SEARCH_RATE, _SEARCH_CAPACITY)
    _core_bucket = TokenBucket(_CORE_RATE, _CORE_CAPACITY)


def classify_url(url: str) -> str | None:
    """按 URL 返回桶名：'search' / 'core' / None（非 GitHub API，不管控）。"""
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return None
    host = (p.hostname or "").lower()
    if host != _API_HOST:
        return None
    path = p.path or "/"
    if path.startswith(_SEARCH_PREFIX):
        return "search"
    return "core"


def _bucket_for(name: str | None) -> TokenBucket | None:
    if name == "search":
        return _search_bucket
    if name == "core":
        return _core_bucket
    return None


def acquire_for_url(url: str) -> None:
    """发请求前调用：按 URL 分类取 1 个令牌，不够就阻塞。非 GitHub API URL 直接返回。"""
    b = _bucket_for(classify_url(url))
    if b is not None:
        b.acquire(1.0)


def update_from_headers(url: str, headers) -> None:
    """响应后调用：读 X-RateLimit-* 头同步桶状态。headers 是 dict-like（HTTPMessage/HTTPError.headers）。

    - 只在是 GitHub API 响应时生效；
    - X-RateLimit-Remaining 缺失/解析失败就静默跳过（别因为头解析问题把请求搞崩）。
    """
    b = _bucket_for(classify_url(url))
    if b is None:
        return
    try:
        rem = headers.get("X-RateLimit-Remaining")
        if rem is None:
            return
        rem_n = int(rem)
        b.set_remaining(rem_n)
    except (ValueError, TypeError, AttributeError):
        # 头格式异常就不管，本地估算继续跑，最多就是稍微保守点
        warnings.warn(f"X-RateLimit-* 头解析异常，忽略；url={url}", stacklevel=2)
