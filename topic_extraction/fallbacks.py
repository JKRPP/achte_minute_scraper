"""Fallback parsers for pre-2013 articles that have no <blockquote>."""

import re

from bs4 import BeautifulSoup

from .round_content import (
    _extract_format_from_topic,
    _finalize_round,
    _group_into_rounds,
    _looks_like_topic,
)
from .round_labels import (
    _match_inline_round_label,
    _match_label_stem,
    _match_round_label,
)
from .text import _linkify_anchors, _normalize_whitespace, _strip_quotes

# Matches lead in paragraph ("Die Themen:")
_THEMEN_INTRO_RE = re.compile(r"Themen?\b.*:\s*$", re.IGNORECASE)

# Matches a single topic in a text ("Das Thema war:")
_THEMA_INTRO_RE = re.compile(
    r"\bThema\b(?:\s+(?:der|des)\s+(\w+))?[^:]{0,60}?:\s*", re.IGNORECASE | re.DOTALL
)

# Matches list items that consist only of a link
_URL_ONLY_RE = re.compile(r"^\S+://\S+$|^\[[^\]]*\]\(\S+\)$")

# Matches a closing sentence end (. ? ! plus optional closing quotes/brackets)
_SENTENCE_END_RE = re.compile(r"[.?!][\"“”„)\]]*\s*$")

# Matches the "vs." separator line between two teams
_VERSUS_LINE_RE = re.compile(r"^vs\.?$", re.IGNORECASE)

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
            # Link lists (social media etc.) are no topic lists
            if item_text and not _URL_ONLY_RE.match(item_text):
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


def _paragraph_lines(p) -> list[str]:
    """
    Splits a paragraph into its non-empty lines and reattaches colons after tags
    """
    lines: list[str] = []
    for line in p.get_text("\n").split("\n"):
        line = _normalize_whitespace(line)
        if not line:
            continue
        if lines and line[0] == ":" and not lines[-1].endswith(":"):
            lines[-1] += line
        else:
            lines.append(line)
    return lines


def _only_has_factsheet(lines: list[str]) -> bool:
    """Checks whether a round label is followed by a factsheet label (and no topic)."""
    for line in lines:
        label = _match_any_round_label(line)
        if _match_label_stem(label.group(2) if label else line):
            return True
    return False


def _inline_round_list_entries(soup: BeautifulSoup) -> list[dict[str, str]]:
    """
    Fallback for pre-2013 articles that list topics as new lines of text with no list.
    """
    entries = []
    for p in soup.find_all("p"):
        lines = _paragraph_lines(p)
        # Break announcements ("Halbfinale 1: Team A vs. Team B") pair teams, they list no topic
        if any(_VERSUS_LINE_RE.match(line) for line in lines):
            continue
        round_entries = _group_into_rounds(lines, _match_any_round_label)

        # A round label paragraph can be followed by the topic in a paragraph of its own
        next_p = p.find_next_sibling("p")
        if round_entries and next_p is not None:
            next_lines = _paragraph_lines(next_p)
            if (
                _only_has_factsheet(lines)
                and round_entries[-1]["Format"] == "unbekannt"
                and not any(_match_any_round_label(line) for line in next_lines)
                and _extract_format_from_topic(" ".join(next_lines)) != "unbekannt"
            ):
                round_entries = _group_into_rounds(
                    lines + next_lines, _match_any_round_label
                )

        # Team lists ("Viertelfinale (Main Break): Team A, Team B") are no topics
        entries.extend(e for e in round_entries if not _is_enumeration(e))

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

        if not remainder or not _looks_like_topic(_strip_quotes(remainder)):
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


def _is_enumeration(entry: dict[str, str]) -> bool:
    """
    Checks whether an entry is a bare enumeration (teams, places) rather than a
    topic: unknown format and no sentence end.
    """
    return entry["Format"] == "unbekannt" and not _SENTENCE_END_RE.search(
        entry["Thema"]
    )
