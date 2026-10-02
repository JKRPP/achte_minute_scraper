"""Entry point: extracts round/topic/factsheet entries from an article page."""

import re

from bs4 import BeautifulSoup, NavigableString

from .fallbacks import (
    _inline_round_list_entries,
    _inline_thema_entries,
    _topic_list_entries,
)
from .round_content import _group_into_rounds
from .round_labels import _split_multi_round_segment
from .text import _linkify_anchors, _normalize_whitespace
from .tournament import _extract_tournament_name, _tournament_name_for_section

# Headers that signify the start of a topic section
_SECTION_HEADER_RE = re.compile(r"^[A-Za-zÀ-ÿ]+(?:\s[A-Za-zÀ-ÿ]+)+:$")
_SECTION_ABBREVIATION_INTRO_RE = re.compile(
    r"Themen\s+de[rs]\s+([A-ZÄÖÜ]{2,6})\s+in\s+der\s+(?:Übersicht|Ubersicht)",
    re.IGNORECASE,
)

# Headers that signify something is not a topic section
_SECTION_HEADING_BLOCKLIST_RE = re.compile(
    r"break|jur(?:y|ier|or)|tabmaster|casefile|equity|rednerinnen|top\s*\d",
    re.IGNORECASE,
)

_SECTION_CITY_PARAGRAPH_MAX_LEN = 40


def extract_topics_from_article(
    article: BeautifulSoup, date, url
) -> list[dict[str, str]]:
    """
    Extracts round/topic/factsheet triples from an article page.
    """
    sections = _section_headings_by_blockquote(article)

    entries = []
    blockquotes = article.find_all("blockquote")
    for blockquote in blockquotes:
        section = sections.get(id(blockquote))
        segments = (
            segment
            for segment in _blockquote_segments(blockquote)
            # Skip decorative splitters
            if any(c.isalnum() for c in segment)
            and not _SECTION_HEADER_RE.match(segment)
        )
        for entry in _group_into_rounds(segments):
            entry["_section"] = section
            entries.append(entry)

    title = _extract_title(article)

    # Fallbacks for articles pre-2013 that do not contain blockquotes as topic sections
    if not blockquotes:
        for fallback in (
            _topic_list_entries,
            _inline_round_list_entries,
            lambda soup: _inline_thema_entries(soup, title),
        ):
            if entries:
                break
            entries = fallback(article)

    tournament_name = _extract_tournament_name(url, title)

    for entry in entries:
        section = entry.pop("_section", None)
        entry["Link"] = url
        entry["Tournament"] = (
            _tournament_name_for_section(section) if section else tournament_name
        )
        entry["Datum"] = date

    return entries


def _section_headings_by_blockquote(soup: BeautifulSoup) -> dict[int, str]:
    """
    Maps each <blockquote> in the article to the name of the
    tournament section it belongs to, for articles covering multiple
    regional tournaments in a single post. Returns an empty mapping for
    ordinary single-tournament articles.
    """
    sections: dict[int, str] = {}
    current: str | None = None

    for tag in soup.find_all(["h3", "p", "blockquote"]):
        if tag.name == "h3":
            text = tag.get_text(strip=True)
            if text:
                current = text
        elif tag.name == "p":
            text = tag.get_text(strip=True)

            abbreviation_match = _SECTION_ABBREVIATION_INTRO_RE.search(text)
            if abbreviation_match:
                current = abbreviation_match.group(1).upper()
                continue

            strongs = tag.find_all(["strong", "b"])
            if (
                text
                and not text.endswith(":")
                and len(text) <= _SECTION_CITY_PARAGRAPH_MAX_LEN
                and len(strongs) == 1
                and strongs[0].get_text(strip=True) == text
                and not _SECTION_HEADING_BLOCKLIST_RE.search(text)
            ):
                current = text
        else:
            if current is not None:
                sections[id(tag)] = current

    if len(set(sections.values())) < 2:
        return {}

    return sections


def _blockquote_segments(blockquote) -> list[str]:
    """
    Flattens a <blockquote> into logical segments (one topic/factsheet/round
    label per segment).
    """
    _linkify_anchors(blockquote)
    segments = []
    elements = blockquote.find_all(
        lambda tag: tag.name == "p"
        or (tag.name == "div" and not tag.find(["p", "div"]))
    )
    for p in elements:
        current = ""
        br_run = 0
        # Keeps adjacent highlighted spots together, even when a label is
        # split across different bold tags ("<b>VR</b><strong>7</strong>:").
        current_is_strong_only = True

        def flush():
            nonlocal current, current_is_strong_only
            if current.strip():
                segments.extend(_split_multi_round_segment(current.strip()))
            current = ""
            current_is_strong_only = True

        for descendant in p.descendants:
            if isinstance(descendant, NavigableString):
                text = str(descendant)
                current += text
                if text.strip():
                    br_run = 0
                    if descendant.parent.name not in ("strong", "b"):
                        current_is_strong_only = False
            elif descendant.name == "br":
                br_run += 1
                if br_run >= 2:
                    flush()
            elif descendant.name in ("strong", "b"):
                # Split on a new highlighted spot
                if not current_is_strong_only:
                    flush()
                br_run = 0
        flush()
    return segments


def _extract_title(soup: BeautifulSoup) -> str:
    heading = soup.find("h2")
    return _normalize_whitespace(heading.get_text()) if heading else ""
