"""Turns a round's raw segments into a topic/factsheet entry with format and language."""

import re
from collections.abc import Callable, Iterable

import pycld2 as cld2

from .data import _BP_MOTION_START, _OPD_MOTION_START
from .round_labels import _match_label_stem, _match_round_label
from .text import _fix_common_typos, _normalize_whitespace, _strip_quotes

# Lineup markers (teams, speakers, judges); a round containing one has no topic
_LINEUP_MARKER_RE = re.compile(
    r"(?<!\S)(Regierung|Reg|Opposition|Opp|(?:Fraktionsfreie|Freie)\s+Redner|FFR"
    r"|(?-i:ER|EO|SR|SO|OG|OO|CG|CO))\s*:"
    r"|(?<!\S)Es\s+jurierten\b",
    re.IGNORECASE,
)

# Text that reads like a BP or OPD motion
_TOPIC_LIKE_RE = re.compile(
    rf"\?\s*$|^(?:{_BP_MOTION_START})\b|^(?:{_OPD_MOTION_START})\b",
    re.IGNORECASE,
)

# BP motion opener anywhere in the text
_BP_FORMAT_RE = re.compile(rf"\b(?:{_BP_MOTION_START})\b", re.IGNORECASE)

# OPD motion opener at the start of a sentence
_OPD_FORMAT_RE = re.compile(rf"(?:^|[:.!?]\s*)(?:{_OPD_MOTION_START})\b", re.IGNORECASE)

# Factsheet label inside a topic ("... Infoslide: ...")
_TRAILING_LABEL_RE = re.compile(
    r"(?<!\S)(Fact(?:sheet)?|Info(?:slide)?|Definition)\s*:", re.IGNORECASE
)

# "inkl." that old articles put in front of factsheet labels ("(inkl. Infoslide)")
_INKL_PREFIX_RE = re.compile(r"^inkl\.?\s*", re.IGNORECASE)

# Footnote marker ("*", "[1]"); footnotes belong to the factsheet
_FOOTNOTE_RE = re.compile(r"^(?:\*+|\[\d+\])")

# Sentence end followed by a new sentence or the end of the text
_SENTENCE_END_RE = re.compile(r"[.?!]+(?=\s+[A-ZÄÖÜ]|\s*$)")

# Unambiguous German/English wording, checked before falling back to CLD2
_CLEAR_GERMAN_RE = re.compile(
    r"(DH|Dieses Haus|begrüßt|bedauert|bereut|würde|Würde|Sollten)"
)
_CLEAR_ENGLISH_RE = re.compile(
    r"(This house|This House|regrets|supports|would|Would|prefers)"
)
# Stray leading bracket left over from a split label
_LEADING_BRACKET_RE = re.compile(r"^\.?\)\s*")
# Control characters, removed before passing text to CLD2
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _group_into_rounds(
    segments: Iterable[str],
    match_label: Callable[[str], re.Match | None] = _match_round_label,
) -> list[dict[str, str]]:
    """Groups segments into rounds by their labels; text before the first label and lineups are dropped."""
    entries = []
    current_round = None
    current_content: list[str] = []

    def finish_round():
        """Finalizes the current round unless it lists a lineup."""
        if any(_LINEUP_MARKER_RE.search(c) for c in current_content):
            return
        entry = _finalize_round(current_round, current_content)
        if entry:
            entries.append(entry)

    for segment in segments:
        label_match = match_label(segment)
        if label_match:
            finish_round()
            current_round = label_match.group(1).strip()
            remainder = label_match.group(2).strip()
            # Unwrap fully parenthesized rounds ("(Runde 1: ...)")
            if segment.startswith("(") and remainder.endswith(")"):
                remainder = remainder[:-1].strip()
            current_content = [remainder] if remainder else []
        elif current_round is not None:
            current_content.append(segment)

    finish_round()
    return entries


def _finalize_round(
    round_label: str | None, content: list[str]
) -> dict[str, str] | None:
    """Turns a round's segments into a {Runde, Thema, Factsheet, Sprache, Format} entry."""
    if round_label is None or not content:
        return None

    topic_index, dropped_indices = _find_topic_index(content)
    topic = content[topic_index]
    factsheet_parts = [
        part
        for idx, part in enumerate(content)
        if idx != topic_index and idx not in dropped_indices
    ]

    if _match_label_stem(topic):
        inline_factsheet, topic = _split_labelled_topic(topic)
        if inline_factsheet:
            factsheet_parts.append(inline_factsheet)
    else:
        # Catch trailing factsheets ("Runde 1: ... Factsheet: ...")
        new_topic, trailing_factsheet = _split_trailing_factsheet(topic)
        if trailing_factsheet:
            topic = new_topic
            factsheet_parts.append(trailing_factsheet)

    # A leading parenthetical belongs to the factsheet; if there already is one, only when labeled
    leading_parenthetical, topic = _split_leading_parenthetical(
        topic, require_label=bool(factsheet_parts)
    )
    if leading_parenthetical:
        factsheet_parts.append(leading_parenthetical)

    stripped_parts = [_strip_factsheet_label(part) for part in factsheet_parts]
    factsheet = _normalize_whitespace(
        _strip_quotes(" ".join(part for part in stripped_parts if part).strip())
    )

    # Fix common typos ("Diese Haus") before detecting the format
    topic = _fix_common_typos(topic)
    topic = _LEADING_BRACKET_RE.sub("", topic)
    factsheet = _fix_common_typos(factsheet)

    topic_format = _extract_format_from_topic(topic)

    # Topic and factsheet are swapped if only the factsheet reads like a motion
    if topic_format == "unbekannt":
        factsheet_format = _extract_format_from_topic(factsheet)
        if factsheet_format != "unbekannt":
            topic_format = factsheet_format
            topic, factsheet = factsheet, topic

    return {
        "Runde": round_label,
        "Thema": _normalize_whitespace(_strip_quotes(topic)),
        "Factsheet": factsheet,
        "Sprache": _detect_language(f"{factsheet} {topic}".strip()),
        "Format": topic_format,
    }


def _find_topic_index(content: list[str]) -> tuple[int, set[int]]:
    """Returns the index of the topic segment and the indices of segments to drop."""
    topic_index = None
    fallback_topic_index = None
    dropped_indices = set()
    # Search backwards, since the topic usually comes last
    for i in range(len(content) - 1, -1, -1):
        stripped = content[i].strip()
        # Factsheet labels, bullet points, parentheticals and footnotes are never the topic
        if (
            _match_label_stem(content[i])
            or stripped.startswith(("-", "–", "—", "•"))
            or (stripped.startswith("(") and stripped.endswith(")"))
            or _FOOTNOTE_RE.match(stripped)
        ):
            continue

        if fallback_topic_index is None:
            fallback_topic_index = i
        if _looks_like_topic(content[i]):
            topic_index = i
            break
        dropped_indices.add(i)

    # No motion-like segment, so fall back to the last non-factsheet one
    if topic_index is None:
        topic_index = (
            fallback_topic_index
            if fallback_topic_index is not None
            else len(content) - 1
        )
        dropped_indices.discard(topic_index)

    return topic_index, dropped_indices


def _strip_factsheet_label(part: str) -> str:
    """Removes a leading "inkl." and "Info:"-style label from a factsheet part."""
    part = _INKL_PREFIX_RE.sub("", part)
    label_match = _match_label_stem(part)
    if label_match:
        # Cut at the colon so multi-word labels ("info slide:") are removed fully
        colon_index = part.find(":", 0, 30)
        cut = colon_index + 1 if colon_index != -1 else label_match.end()
        part = part[cut:].strip()
    return part


def _looks_like_topic(text: str) -> bool:
    """Checks whether text reads like a motion (see _TOPIC_LIKE_RE)."""
    return bool(_TOPIC_LIKE_RE.search(text.strip()))


def _split_labelled_topic(text: str) -> tuple[str, str]:
    """Splits a "Factsheet: ..." topic into (factsheet, topic), the topic being the last sentence."""
    if "\n" in text:
        prefix, _, last = text.rpartition("\n")
        if prefix.strip() and last.strip():
            return prefix.strip(), last.strip()

    matches = list(_SENTENCE_END_RE.finditer(text))
    for match in reversed(matches):
        prefix, last = text[: match.end()], text[match.end() :]
        if prefix.strip() and last.strip():
            return prefix.strip(), last.strip()

    return "", text


def _split_trailing_factsheet(text: str) -> tuple[str, str]:
    """Splits a trailing "Factsheet: ..." off the topic, returning (topic, factsheet)."""
    match = _TRAILING_LABEL_RE.search(text)
    if not match or match.start() == 0:
        return text, ""

    topic = text[: match.start()].strip()
    factsheet = text[match.start() :].strip()
    if not topic or not factsheet:
        return text, ""

    return topic, factsheet


def _split_leading_parenthetical(text: str, require_label: bool) -> tuple[str, str]:
    """Splits a leading parenthetical off the topic, returning (parenthetical, topic)."""
    stripped = text.lstrip()
    if not stripped.startswith("("):
        return "", text

    depth = 0
    close_index = -1
    for i, char in enumerate(stripped):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                close_index = i
                break
    if close_index == -1:
        return "", text

    inner = stripped[1:close_index].strip()

    if require_label and not _match_label_stem(_INKL_PREFIX_RE.sub("", inner)):
        return "", text

    remainder = stripped[close_index + 1 :].strip()
    if not remainder:
        return "", text

    return inner, remainder


def _extract_format_from_topic(topic: str) -> str:
    """Classifies a topic as "BP", "OPD" or "unbekannt" from its wording."""
    topic_to_match = topic.strip().replace('"', "")

    if _BP_FORMAT_RE.search(topic_to_match):
        return "BP"

    if "?" in topic:
        return "OPD"

    if _OPD_FORMAT_RE.search(topic_to_match):
        return "OPD"

    return "unbekannt"


def _detect_language(text: str) -> str:
    """Detects a topic's language from clear keywords, falling back to Google's CLD2."""
    if _CLEAR_GERMAN_RE.search(text):
        return "GERMAN"

    if _CLEAR_ENGLISH_RE.search(text):
        return "ENGLISH"

    clean_text = _CONTROL_CHAR_RE.sub("", text)
    _, _, details = cld2.detect(clean_text, hintLanguage="de")
    return details[0][0] if details else "unknown"
