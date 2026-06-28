"""test_ratelimit：ratelimit 令牌桶模块离线单测。

覆盖：
  - TokenBucket 令牌发放/等待/注入时钟
  - classify_url 分类 search/core/非GitHub
  - acquire_for_url / update_from_headers 桶分发
  - 非 GitHub URL 直通（不等待、不改桶）
  - 坏 X-RateLimit-* 头 warning 但不崩
  - _reset_buckets_for_tests 重置
  - 并发 acquire 线程安全（用确定性 fast-clock 锁序验证）
"""

from __future__ import annotations

import threading
import time
import warnings

import pytest

from skillbrew import ratelimit
from skillbrew.ratelimit import TokenBucket, classify_url

# ---------- 基础 ----------


@pytest.fixture(autouse=True)
def _reset_buckets():
    """每个用例前把模块单例桶重置到满，避免串扰。"""
    ratelimit._reset_buckets_for_tests()
    yield
    ratelimit._reset_buckets_for_tests()


def test_classify_url_search():
    assert classify_url("https://api.github.com/search/repositories?q=foo") == "search"


def test_classify_url_core():
    assert classify_url("https://api.github.com/repos/foo/bar") == "core"
    assert classify_url("https://api.github.com/repos/foo/bar/git/trees/main?recursive=1") == "core"


def test_classify_url_raw_is_none():
    assert classify_url("https://raw.githubusercontent.com/foo/bar/main/README.md") is None


def test_classify_url_external_is_none():
    assert classify_url("https://api.bilibili.com/x/web-interface/view") is None
    assert classify_url("https://example.com/foo") is None


def test_classify_url_malformed_is_none():
    assert classify_url("not a url") is None
    assert classify_url("") is None


# ---------- TokenBucket 单线程 ----------


def test_bucket_full_immediate_acquire():
    sleeps = []
    clock = [100.0]
    b = TokenBucket(
        rate=1.0, capacity=3, time_func=lambda: clock[0], sleep_func=lambda s: sleeps.append(s)
    )
    for _ in range(3):
        b.acquire(1.0)
    assert sleeps == []
    assert abs(b.remaining() - 0.0) < 1e-6


def test_bucket_empty_must_wait():
    sleeps = []
    clock = [100.0]
    b = TokenBucket(
        rate=1.0, capacity=2, time_func=lambda: clock[0], sleep_func=lambda s: sleeps.append(s)
    )
    b.acquire(2.0)  # 拿光
    assert abs(b.remaining()) < 1e-6

    # 再拿 1 个：需要等 1 秒（rate=1/s → 每秒补 1 个）
    def _advance(d):
        clock[0] += d

    # 把 sleep 替换成推进时钟，模拟"真睡了 s 秒"
    real_sleep = sleeps.append

    def fake_sleep(s):
        real_sleep(s)
        clock[0] += s

    b._sleep = fake_sleep
    b.acquire(1.0)
    assert sleeps == [1.0]
    # 刚补了 1 个又被拿走，剩 0
    assert abs(b.remaining()) < 1e-6


def test_bucket_refills_over_time():
    clock = [0.0]
    b = TokenBucket(rate=2.0, capacity=5, time_func=lambda: clock[0])
    b.acquire(5.0)
    assert abs(b.remaining()) < 1e-6
    # 过了 1.5 秒，应该补 3 个
    clock[0] += 1.5
    assert abs(b.remaining() - 3.0) < 1e-6
    # 不能超过 capacity
    clock[0] += 100.0
    assert abs(b.remaining() - 5.0) < 1e-6


def test_set_remaining_clamps():
    clock = [0.0]
    b = TokenBucket(rate=1.0, capacity=5, time_func=lambda: clock[0])
    b.set_remaining(100.0)  # 超了 capacity → clamp 到 5
    assert abs(b.remaining() - 5.0) < 1e-6
    b.set_remaining(-3.0)  # 负 → clamp 到 0
    assert abs(b.remaining()) < 1e-6


# ---------- 模块级桶分发 ----------


def test_acquire_for_url_search_consumes_search_bucket_only():
    # 用光 search 桶
    for _ in range(10):
        ratelimit.acquire_for_url("https://api.github.com/search/repositories?q=x")
    # 记录 search 桶空后下一次 acquire 的 sleep 时间；core 桶应仍满
    sleeps = []
    ratelimit._search_bucket._sleep = lambda s: sleeps.append(s)
    # 推进时钟让 search 桶补 1 个，否则会一直阻塞；
    # 先替换 sleep 为推进时钟
    clock = [time.monotonic()]
    ratelimit._search_bucket._time = lambda: clock[0]

    def fake_sleep(s):
        sleeps.append(s)
        clock[0] += s

    ratelimit._search_bucket._sleep = fake_sleep
    ratelimit.acquire_for_url("https://api.github.com/search/repositories?q=x")
    assert sleeps, "search 桶空了必须 sleep"
    # core 桶应该还是满的（60 个）
    assert abs(ratelimit._core_bucket.remaining() - 60.0) < 1e-6


def test_acquire_for_url_non_github_noop():
    # raw/external URL 完全不碰桶，桶保持满
    ratelimit.acquire_for_url("https://raw.githubusercontent.com/x/y/z/README.md")
    ratelimit.acquire_for_url("https://api.bilibili.com/x")
    assert abs(ratelimit._search_bucket.remaining() - ratelimit._SEARCH_CAPACITY) < 1e-6
    assert abs(ratelimit._core_bucket.remaining() - ratelimit._CORE_CAPACITY) < 1e-6


def test_update_from_headers_syncs_remaining():
    # 把 core 桶设到只剩 3 个，模拟服务器权威头
    class H(dict):
        pass

    h = H({"X-RateLimit-Remaining": "3"})
    ratelimit.update_from_headers("https://api.github.com/repos/foo/bar", h)
    assert abs(ratelimit._core_bucket.remaining() - 3.0) < 1e-6
    # search 桶未动
    assert abs(ratelimit._search_bucket.remaining() - ratelimit._SEARCH_CAPACITY) < 1e-6


def test_update_from_headers_missing_is_noop():
    ratelimit.update_from_headers("https://api.github.com/repos/foo/bar", {})
    # 桶保持满
    assert abs(ratelimit._core_bucket.remaining() - ratelimit._CORE_CAPACITY) < 1e-6


def test_update_from_headers_bad_value_warns_but_doesnt_crash():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        ratelimit.update_from_headers(
            "https://api.github.com/search/repositories?q=x",
            {"X-RateLimit-Remaining": "not-a-number"},
        )
    assert any("X-RateLimit" in str(wi.message) for wi in w)
    # 桶状态没崩
    assert ratelimit._search_bucket.remaining() >= 0


def test_update_from_headers_non_github_noop():
    # 非 GitHub URL 不管 headers 里有啥，不动桶
    ratelimit.update_from_headers("https://example.com/foo", {"X-RateLimit-Remaining": "0"})
    assert abs(ratelimit._search_bucket.remaining() - ratelimit._SEARCH_CAPACITY) < 1e-6
    assert abs(ratelimit._core_bucket.remaining() - ratelimit._CORE_CAPACITY) < 1e-6


# ---------- 线程安全（烟雾级） ----------


def test_concurrent_acquires_no_race():
    """N 个线程各 acquire M 次，总消耗 = N*M 个令牌；用固定 fast-clock 避免真睡。"""
    rate = 1000.0  # 每秒 1000 个 → 基本不阻塞
    cap = 100.0
    clock = [0.0]
    b = TokenBucket(rate=rate, capacity=cap, time_func=lambda: clock[0])
    # 初始满
    threads = []
    n_threads = 8
    per_thread = 10

    def worker():
        for _ in range(per_thread):
            b.acquire(1.0)

    for _ in range(n_threads):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    # 初始 cap=100 > 总消耗 80，应该全部立即可拿、剩 20
    assert abs(b.remaining() - (cap - n_threads * per_thread)) < 1e-6


# ---------- reset 工具 ----------


def test_reset_buckets_for_tests_restores_full():
    ratelimit._core_bucket.acquire(60.0)
    ratelimit._search_bucket.acquire(10.0)
    assert abs(ratelimit._core_bucket.remaining()) < 1e-6
    assert abs(ratelimit._search_bucket.remaining()) < 1e-5, "search bucket leaked beyond tolerance"
    ratelimit._reset_buckets_for_tests()
    assert abs(ratelimit._core_bucket.remaining() - ratelimit._CORE_CAPACITY) < 1e-6
    assert abs(ratelimit._search_bucket.remaining() - ratelimit._SEARCH_CAPACITY) < 1e-6
