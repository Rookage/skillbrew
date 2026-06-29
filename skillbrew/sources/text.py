"""纯文本 / 本地文件 adapter（兜底）：把内容或文件直接写 transcript.txt。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ._helpers import write_json
from .base import register


@dataclass
class TextFetchResult:
    """文本/网页/文档获取结果（视频无关源）。"""

    title: str
    text: str
    text_path: Path
    meta_path: Path


def fetch_text(
    source: str,
    out_dir: Path,
    *,
    title: str = "",
) -> TextFetchResult:
    """将裸文本或文件内容写入 transcript.txt。

    source: 文本内容，或 .txt/.md/.pdf 文件的路径。
    out_dir: 输出目录（自动建）。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    path = Path(source)
    if path.exists() and path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        title = title or path.stem
    else:
        text = source
        title = title or "直接输入文本"

    text_path = out_dir / "transcript.txt"
    text_path.write_text(text, encoding="utf-8")
    meta = {"title": title, "source": "direct" if not path.exists() else str(path)}
    write_json(out_dir / "meta.json", meta)

    return TextFetchResult(
        title=title,
        text=text,
        text_path=text_path,
        meta_path=out_dir / "meta.json",
    )


@register
class TextAdapter:
    """纯文本/本地文件源适配器（兜底）。"""

    name = "text"
    priority = 100  # 最后匹配
    is_video = False
    required_bins: tuple[str, ...] = ()

    @classmethod
    def detect(cls, src: str) -> bool:
        # 兜底：所有输入都能当文本处理
        return True

    @classmethod
    def resolve_subdir(cls, src: str) -> str:
        p = Path(src)
        if p.exists() and p.is_file():
            return f"file_{p.stem}"
        return f"text_{hash(src) & 0xFFFFFFFF:08x}"

    def fetch(self, src: str, out_dir: Path, *, title: str = "", **_kw: object) -> TextFetchResult:
        return fetch_text(src, out_dir, title=title)


__all__ = ["TextFetchResult", "fetch_text", "TextAdapter"]
