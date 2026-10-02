"""Fallback parsers for pre-2013 articles that have no <blockquote>."""

import re

from bs4 import BeautifulSoup

from .round_content import _finalize_round, _group_into_rounds, _looks_like_topic
from .round_labels import _match_inline_round_label, _match_round_label
from .text import _linkify_anchors, _normalize_whitespace

# Matches lead in paragraph ("Die Themen:")
_THEMEN_INTRO_RE = re.compile(r"Themen?\b.*:\s*$", re.IGNORECASE)

# Matches a single topic in a text ("Das Thema war:")
_THEMA_INTRO_RE = re.compile(
    r"\bThema\b(?:\s+(?:der|des)\s+(\w+))?[^:]{0,60}?:\s*", re.IGNORECASE | re.DOTALL
)

# Finds a round label if only one topic is mentioned in the article
_TITLE_ROUND_RE = re.compile(
    r"(Vorrunde|Runde|Round)\s*(\d+)(?:\s*/\s*\d+)?"
    r"|(Viertelfinale|Halbfinale|Achtelfinale|Finale)",
    re.IGNORECASE,
)


def _topic_list_segments(soup: BeautifulSoup) -> list[str]:
    """
    Fallback for pre-2013 articles, which list topics as a <ul>/<ol> of
    "<Round>: <Topic>" items introduced by a plain paragraph.
    """
    segments = []
    for p in soup.find_all("p"):
        text = _normalize_whitespace(p.get_text())
        if not _THEMEN_INTRO_RE.search(text):
            continue

        list_tag = p.find_next_sibling(["ul", "ol"])
        if list_tag is None:
            continue

        _linkify_anchors(list_tag)
        for li in list_tag.find_all("li", recursive=False):
            item_text = _normalize_whitespace(li.get_text())
            if item_text:
                segments.append(item_text)

    return segments


def _topic_list_entries(soup: BeautifulSoup) -> list[dict[str, str]]:
    """
    Fallback for pre-2013 articles with list items (some with labels some without)
    """
    segments = _topic_list_segments(soup)
    if segments and not any(_match_round_label(s) for s in segments):
        entries = (
            _finalize_round(f"VR{i + 1}", [segment])
            for i, segment in enumerate(segments)
        )
        return [entry for entry in entries if entry]

    return _group_into_rounds(segments)


def _match_any_round_label(line: str):
    return _match_round_label(line) or _match_inline_round_label(line)


def _inline_round_list_entries(soup: BeautifulSoup) -> list[dict[str, str]]:
    """
    Fallback for pre-2013 articles that list topics as new lines of text with no list.
    """
    entries = []
    for p in soup.find_all("p"):
        lines = (_normalize_whitespace(line) for line in p.get_text("\n").split("\n"))
        entries.extend(
            _group_into_rounds([line for line in lines if line], _match_any_round_label)
        )

    return entries


def _inline_thema_entries(soup: BeautifulSoup, title: str) -> list[dict[str, str]]:
    """
    Fallback for pre-2013 single-round-per-article posts
    """
    entries = []
    for p in soup.find_all("p"):
        text = _normalize_whitespace(p.get_text(" "))
        match = _THEMA_INTRO_RE.search(text)
        if not match:
            continue

        remainder = text[match.end() :].strip()
        if not remainder:
            next_p = p.find_next_sibling("p")
            remainder = _normalize_whitespace(next_p.get_text(" ")) if next_p else ""

        if not remainder or not _looks_like_topic(remainder):
            continue

        round_label = _round_label_from_title(title) or match.group(1) or "Thema"
        entry = _finalize_round(round_label, [remainder])
        if entry:
            entries.append(entry)
        break  # Only one topic is ever expected in this article shape.

    return entries


def _round_label_from_title(title: str) -> str | None:
    match = _TITLE_ROUND_RE.search(title)
    if not match:
        return None
    if match.group(1):
        return f"{match.group(1).capitalize()} {match.group(2)}"
    return match.group(3).capitalize()
