"""Small text-cleanup helpers shared across the topic extraction modules."""

import re

from .data import _COMMON_TYPO_RE, _COMMON_TYPOS

_QUOTE_CHARS = "\"'„“”‚‘’«»"


def _linkify_anchors(blockquote) -> None:
    """
    Replaces <a href="..."> tags with a "[text](href)" markdown-style
    string, so links formatted as words survive being flattened to
    plain text.
    """
    for a in blockquote.find_all("a"):
        href = a.get("href", "").strip()
        text = a.get_text().strip()
        a.replace_with(f"[{text}]({href})" if href else text)


def _fix_common_typos(text: str) -> str:
    """Corrects known common typos (see common_typos.json) in a topic/factsheet."""
    if not text:
        return text
    return _COMMON_TYPO_RE.sub(lambda m: _COMMON_TYPOS[m.group(0).lower()], text)


def _normalize_whitespace(text: str) -> str:
    """Collapses internal whitespace (e.g. single-<br/> line wraps) to single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def _strip_quotes(text: str) -> str:
    """Strips a single leading/trailing quote mark, if both are present."""
    if len(text) >= 2 and text[0] in _QUOTE_CHARS and text[-1] in _QUOTE_CHARS:
        text = text[1:-1].strip()
    return text
