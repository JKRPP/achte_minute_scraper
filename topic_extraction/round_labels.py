"""Recognizing round labels ("Runde 1:", "VR2.", ...) and splitting segments on them."""

import re

from .data import _KNOWN_ROUND_LABELS, _KNOWN_ROUND_PREFIXES, _NUMBERED_LABEL_RE
from .text import _normalize_whitespace

_LABEL_STEMS = ("info", "fact", "definition", "beispiel")

_LABEL_WORD_RE = re.compile(r"^([A-Za-zÀ-ÿ]+)\s*:?\s*")

_LABEL_GROUP = r"((?:[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]*\s?){1,4}[0-9]{0,3})(?:\s*\([^)]*\))?"

# Don't detect colons as labels if followed by a non-capitalized letter (Polizist:innen)
_LABEL_COLON = r":(?![a-zäöüß])"

_ROUND_LABEL_LINE_RE = re.compile(
    rf"^\(?{_LABEL_GROUP}{_LABEL_COLON}\s*(.*)$", re.DOTALL
)

_INLINE_ROUND_LABEL_LINE_RE = re.compile(
    rf"^\(?{_LABEL_GROUP}\.(?!\s*[a-zäöüß])\s*(.*)$", re.DOTALL
)

_EMBEDDED_ROUND_LABEL_RE = re.compile(rf"(?:^|(?<=\s))\(?{_LABEL_GROUP}{_LABEL_COLON}")


def _match_label_stem(text: str) -> re.Match | None:
    """
    Matches a leading factsheet-style label word ("Info", "Fact", "Definition",
    "Beispiel", ...), or returns None if text doesn't start with one.
    """
    match = _LABEL_WORD_RE.match(text)
    if match and match.group(1).lower().startswith(_LABEL_STEMS):
        return match
    return None


def _split_multi_round_segment(segment: str) -> list[str]:
    """
    Splits a segment holding several "Runde N: ..." entries glued together
    by a single <br> into its different rounds
    """
    matches = [
        m
        for m in _EMBEDDED_ROUND_LABEL_RE.finditer(segment)
        if _is_known_round_label(m.group(1))
    ]
    if len(matches) <= 1:
        return [segment]

    pieces = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(segment)
        pieces.append(segment[match.start() : end].strip())
    return pieces


def _match_round_label(segment: str) -> re.Match | None:
    """
    Remove colon-labels from text until one label matches the expected
    round label expression
    """
    match = _ROUND_LABEL_LINE_RE.match(segment)
    while match:
        label = match.group(1)
        if any(word.startswith(_LABEL_STEMS) for word in label.lower().split()):
            return None
        if _is_known_round_label(label):
            return match
        match = _ROUND_LABEL_LINE_RE.match(match.group(2))
    return None


def _is_known_round_label(label: str) -> bool:
    """Checks whether a matched label is a legitimate round label."""
    normalized = _normalize_whitespace(label).lower()
    if normalized in _KNOWN_ROUND_LABELS:
        return True
    prefix_match = _NUMBERED_LABEL_RE.match(normalized)
    return bool(prefix_match and prefix_match.group(1) in _KNOWN_ROUND_PREFIXES)


def _match_inline_round_label(line: str) -> re.Match | None:
    """Matches a "VR1. ..." style line (period instead of colon)."""
    match = _INLINE_ROUND_LABEL_LINE_RE.match(line)
    if match and _is_known_round_label(match.group(1)):
        return match
    return None
