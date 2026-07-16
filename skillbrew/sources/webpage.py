"""网页 adapter（D24：抓取网页正文写 transcript.txt）。"""

from __future__ import annotations

import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ._helpers import UA, write_json
from .base import register
from .text import TextFetchResult  # 复用 TextFetchResult 数据结构

_HTML_STRIP = re.compile(r"<[^>]+>")
_BLANK_LINE = re.compile(r"\n{3,}")


def _clean_html(html: str) -> str:
    """从 HTML 中提取可读文本：去 script/style，取 body 正文，合并多余空行。"""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    body = soup.body or soup
    text = body.get_text(separator="\n", strip=True)
    text = _BLANK_LINE.sub("\n\n", text)
    return text.strip()


def _og_title(soup: BeautifulSoup) -> str:
    tag = soup.find("meta", property="og:title")
    if tag is None:
        return ""
    content = tag.get("content")
    return (str(content or "")).strip() if content else ""


def _tag_text(soup: BeautifulSoup, tag: str) -> str:
    el = soup.find(tag)
    return (el.get_text(strip=True) or "") if el else ""


def fetch_webpage(
    source: str,
    out_dir: Path,
    *,
    timeout: float = 30.0,
) -> TextFetchResult:
    """抓取一个网页，提取正文写入 transcript.txt。

    source: 网页 URL（https 开头）。
    out_dir: 输出目录（自动建）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    r = requests.get(source, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"

    html = r.text
    text = _clean_html(html)

    # 取标题：优先 og:title → <title> → URL
    soup = BeautifulSoup(html, "html.parser")
    title = _og_title(soup) or _tag_text(soup, "title") or source.rsplit("/", 1)[-1]

    text_path = out_dir / "transcript.txt"
    text_path.write_text(text, encoding="utf-8")
    meta = {"url": source, "title": title, "charset": r.encoding or "utf-8"}
    write_json(out_dir / "meta.json", meta)

    return TextFetchResult(
        title=title,
        text=text,
        text_path=text_path,
        meta_path=out_dir / "meta.json",
    )


@register
class WebpageAdapter:
    """网页源适配器。"""

    name = "web"
    priority = 50
    is_video = False
    required_bins: tuple[str, ...] = ()

    @classmethod
    def detect(cls, src: str) -> bool:
        # http(s) 开头的都算网页；视频源（bilibili/douyin/youtube）因为 priority 更低会先匹配
        return src.startswith("http://") or src.startswith("https://")

    @classmethod
    def resolve_subdir(cls, src: str) -> str:
        return f"web_{hash(src) & 0xFFFFFFFF:08x}"

    def fetch(self, src: str, out_dir: Path, **_kw: object) -> TextFetchResult:
        return fetch_webpage(src, out_dir)


# 注：TextFetchResult 定义在 text.py；webpage/text 两个 adapter 共享它。
# 这里 re-export 方便外部 `from skillbrew.sources.webpage import TextFetchResult`
__all__ = ["fetch_webpage", "TextFetchResult", "WebpageAdapter"]
