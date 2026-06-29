"""P3-1：sources 适配层单测——分发正确性 + YouTube bug 回归。

行为零改动原则：只测「哪个源匹配到哪个 adapter」这种纯逻辑，不真正下载。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillbrew import ingest
from skillbrew.sources import (
    ADAPTERS,
    BVID_RE,
    DOUYIN_ID_RE,
    YOUTUBE_RE,
    BiliFetchResult,
    DouyinFetchResult,
    TextFetchResult,
    YoutubeFetchResult,
    detect_adapter,
    fetch_bilibili,
    fetch_douyin,
    fetch_text,
    fetch_webpage,
    fetch_with_adapter,
    fetch_youtube,
    is_video_source,
    parse_bvid,
    parse_douyin_id,
    parse_youtube_id,
    required_bins_for,
    resolve_short_url,
    resolve_subdir,
    source_type,
)

# ---- 1. 注册表基础结构 ----

def test_adapters_registered_in_priority_order() -> None:
    """5 个 adapter 必须按 priority 升序注册。"""
    names = [a.name for a in ADAPTERS]
    assert names == ["bilibili", "douyin", "youtube", "web", "text"]
    prios = [a.priority for a in ADAPTERS]
    assert prios == sorted(prios)
    # 视频源都在网页/文本前
    video_names = {a.name for a in ADAPTERS if a.is_video}
    assert video_names == {"bilibili", "douyin", "youtube"}


def test_each_adapter_has_required_bins() -> None:
    """视频源需要 ffmpeg（douyin/youtube 还需 yt-dlp），web/text 不需外部二进制。"""
    by_name = {a.name: a for a in ADAPTERS}
    assert "ffmpeg" in by_name["bilibili"].required_bins
    assert {"ffmpeg", "yt-dlp"}.issubset(set(by_name["douyin"].required_bins))
    assert {"ffmpeg", "yt-dlp"}.issubset(set(by_name["youtube"].required_bins))
    assert by_name["web"].required_bins == ()
    assert by_name["text"].required_bins == ()


# ---- 2. detect_adapter 正确分发 ----

@pytest.mark.parametrize(
    "src, expected_name, video",
    [
        ("https://www.bilibili.com/video/BV1xx411c7mD", "bilibili", True),
        ("BV1xx411c7mD", "bilibili", True),
        ("https://v.douyin.com/abcdef/", "douyin", True),
        ("7384920123456789012", "douyin", True),
        # ⚠️ YouTube bug 回归：这两种 URL 以前在 ingest._main 里落到 webpage 分支
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube", True),
        ("https://youtu.be/dQw4w9WgXcQ", "youtube", True),
        ("https://www.youtube.com/shorts/abcdefgh123", "youtube", True),
        ("https://www.youtube.com/embed/dQw4w9WgXcQ", "youtube", True),
        ("https://example.com/article", "web", False),
        ("http://foo.bar/baz", "web", False),
        ("hello world 纯文本", "text", False),
    ],
)
def test_detect_adapter_routes_correctly(src: str, expected_name: str, video: bool) -> None:
    """各种输入必须命中正确的 adapter；视频源标记正确。"""
    cls = detect_adapter(src)
    assert cls is not None, f"src={src!r} 应命中 adapter"
    assert cls.name == expected_name, f"src={src!r} 命中 {cls.name!r}，期望 {expected_name!r}"
    assert is_video_source(src) is video
    assert source_type(src) == expected_name


def test_text_fallback_never_returns_none() -> None:
    """兜底：任何乱码字符串都至少命中 text adapter，不会返回 None。"""
    for s in ["", "   ", "!!!@@@###", "/not/a/real/path.txt"]:
        a = detect_adapter(s)
        assert a is not None
        assert a.name == "text"


def test_required_bins_for_youtube_is_ffmpeg_ytdlp() -> None:
    """⚠️ YouTube bug 回归：预检时 YouTube 必须需要 ffmpeg + yt-dlp（不能当网页）。"""
    bins = required_bins_for("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert "ffmpeg" in bins
    assert "yt-dlp" in bins


# ---- 3. 正则 / parse 工具 ----

def test_parse_bvid_from_url_and_bare() -> None:
    assert parse_bvid("https://www.bilibili.com/video/BV1xx411c7mD?p=2") == "BV1xx411c7mD"
    assert parse_bvid("BV1xx411c7mD") == "BV1xx411c7mD"


def test_parse_youtube_id_variants() -> None:
    """⚠️ YouTube bug 回归：watch / youtu.be / shorts / embed 都能提取 ID。"""
    assert parse_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert parse_youtube_id("https://www.youtube.com/shorts/abcdefgh123") == "abcdefgh123"
    assert parse_youtube_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"


def test_parse_douyin_id_from_url_and_bare() -> None:
    assert parse_douyin_id("https://www.douyin.com/video/7384920123456789012") == "7384920123456789012"
    assert parse_douyin_id("7384920123456789012") == "7384920123456789012"


def test_bvid_re_does_not_match_pure_digits() -> None:
    """B站 BV 号必须 BV 开头，纯数字不能当 BVID（否则会抢抖音 ID）。"""
    assert BVID_RE.search("7384920123456789012") is None


def test_youtube_re_matches_shorts() -> None:
    """⚠️ YouTube bug 回归：旧正则漏了 /shorts/ 和 /embed/，新正则要覆盖。"""
    assert YOUTUBE_RE.search("https://www.youtube.com/shorts/abcdefgh123")
    assert YOUTUBE_RE.search("https://www.youtube.com/embed/dQw4w9WgXcQ")


# ---- 4. resolve_subdir 输出前缀 ----

def test_resolve_subdir_prefixes() -> None:
    assert resolve_subdir("BV1xx411c7mD").startswith("BV1")  # bilibili 直接用 BV 号
    assert resolve_subdir("7384920123456789012").startswith("douyin_")
    assert resolve_subdir("https://youtu.be/dQw4w9WgXcQ").startswith("yt_")
    assert resolve_subdir("https://example.com/").startswith("web_")
    assert resolve_subdir("hello world").startswith("text_")


# ---- 5. backward compat：skillbrew.ingest 必须 re-export 所有旧路径符号 ----

def test_ingest_reexports_preserved() -> None:
    """现有测试 monkeypatch `skillbrew.ingest.fetch_*`——这些属性必须存在。"""
    # 数据类
    assert ingest.BiliFetchResult is BiliFetchResult
    assert ingest.DouyinFetchResult is DouyinFetchResult
    assert ingest.YoutubeFetchResult is YoutubeFetchResult
    assert ingest.TextFetchResult is TextFetchResult
    # fetch 函数（关键：test_cli_binary_check.py monkeypatch 这三个路径）
    assert ingest.fetch_bilibili is fetch_bilibili
    assert ingest.fetch_douyin is fetch_douyin
    assert ingest.fetch_youtube is fetch_youtube
    assert ingest.fetch_webpage is fetch_webpage
    assert ingest.fetch_text is fetch_text
    # 正则/parse
    assert ingest.BVID_RE is BVID_RE
    assert ingest.DOUYIN_ID_RE is DOUYIN_ID_RE
    assert ingest.YOUTUBE_RE is YOUTUBE_RE
    assert ingest.parse_bvid is parse_bvid
    assert ingest.parse_douyin_id is parse_douyin_id
    assert ingest.parse_youtube_id is parse_youtube_id
    # 短链解析（旧名字是 ingest._resolve_short_url，新公开名 resolve_short_url）
    assert hasattr(ingest, "resolve_short_url")
    assert ingest.resolve_short_url is resolve_short_url
    # 分发函数
    assert ingest.detect_adapter is detect_adapter
    assert ingest.fetch_with_adapter is fetch_with_adapter
    assert ingest.is_video_source is is_video_source


# ---- 6. fetch_with_adapter 实际路由（monkeypatch 掉真正下载）----

def test_fetch_with_adapter_dispatches_to_bilibili(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    sentinel = BiliFetchResult(
        bvid="BV1xx411c7mD", aid=1, cid=2, title="t", duration=3,
        pic="", video_path=tmp_path / "v.mp4", audio_path=tmp_path / "a.mp3",
        meta_path=tmp_path / "meta.json",
    )

    def _fake(src: str, out: Path, **kw: object) -> BiliFetchResult:
        assert src.startswith("BV")
        assert kw.get("qn") == 32  # bilibili 接收 qn 参数
        return sentinel

    monkeypatch.setattr("skillbrew.sources.bilibili.fetch_bilibili", _fake)
    r, cls = fetch_with_adapter("BV1xx411c7mD", tmp_path, qn=32)
    assert cls.name == "bilibili"
    assert r is sentinel


def test_fetch_with_adapter_dispatches_youtube_not_webpage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """⚠️ YouTube bug 回归：YouTube URL 必须走 youtube adapter，绝对不能走 web。"""
    called = {"yt": 0, "web": 0}

    def _fake_yt(src: str, out: Path) -> YoutubeFetchResult:
        called["yt"] += 1
        return YoutubeFetchResult(
            video_id="dQw4w9WgXcQ", title="t", duration=0,
            video_path=out / "v.mp4", audio_path=out / "a.mp3",
            subtitle_path=None, meta_path=out / "meta.json",
        )

    def _fake_web(src: str, out: Path) -> TextFetchResult:  # pragma: no cover - 不应被调用
        called["web"] += 1
        raise AssertionError("YouTube URL 绝不能被 webpage adapter 处理（回归 bug）")

    monkeypatch.setattr("skillbrew.sources.youtube.fetch_youtube", _fake_yt)
    monkeypatch.setattr("skillbrew.sources.webpage.fetch_webpage", _fake_web)

    for url in [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
    ]:
        r, cls = fetch_with_adapter(url, tmp_path)
        assert cls.name == "youtube", f"{url} 命中 {cls.name}，期望 youtube"
    assert called["yt"] == 2
    assert called["web"] == 0


def test_fetch_with_adapter_text_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """乱码兜底：走 text adapter。"""
    sentinel = TextFetchResult(title="t", text="x", text_path=tmp_path / "t.txt", meta_path=tmp_path / "m.json")

    def _fake(src: str, out: Path, **kw: object) -> TextFetchResult:
        return sentinel

    monkeypatch.setattr("skillbrew.sources.text.fetch_text", _fake)
    r, cls = fetch_with_adapter("!!!乱入!!!", tmp_path)
    assert cls.name == "text"
    assert r is sentinel
