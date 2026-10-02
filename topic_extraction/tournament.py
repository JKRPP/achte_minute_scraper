"""Deriving tournament names (and regional championship abbreviations)."""

import re

from .data import _TOURNAMENT_NAME_OVERRIDES, _TOURNAMENT_TITLE_REPLACEMENTS

_REGIONALMEISTERSCHAFTEN_RE = re.compile(r"Regionalmeisterschaften?", re.IGNORECASE)

# Splits "<winner> gewinnt <tournament>" style headlines
_WINNER_PREFIX_RE = re.compile(
    r"(?:gewinnt|gewinnen|siegreich|wins|triumphieren|triumphiert|Sieger|siegt?)[- ](?:beim|den|die|das|dem|des|der|einen?|eine[mnrs]?|d[iea]|de[mnrs]?|the)?\s*(.+)$",
    re.IGNORECASE,
)

_TITLE_REPLACEMENTS = [
    (re.compile(re.escape(large_description), re.IGNORECASE), replacement)
    for large_description, replacement in _TOURNAMENT_TITLE_REPLACEMENTS.items()
]

_DATEN_UND_ERGEBNISSE_RE = re.compile(
    r"^(?:Die\s+)?(.+?)\s+Daten\s+Und\s+Ergebnisse$", re.IGNORECASE
)

_BREAK_SUFFIX_RE = re.compile(
    r"\s+(?:Der|Die)?\s*Breaks?"
    r"(?:\s+Und\s+Halbfinals?)?"
    r"(?:\s+Ins\s+(?:Viertelfinale|Halbfinale|Finale|Achtelfinale))?"
    r"(?:\s+\d+)?\s*$",
    re.IGNORECASE,
)

_OVERVIEW_SUFFIX_RE = re.compile(
    r"\s+(?:Der|Die|Im)?\s*(?:Ergebnisse|U(?:e|ü)?berblick|U(?:e|ü)?bersicht)(?:\s+Des\s+.+)?\s*$",
    re.IGNORECASE,
)

_PREPOSITION_YEAR_SUFFIX_RE = re.compile(
    r"(?:\s+(?:in|bei|beim|am|im|vor|nach|aus|zu|vom|v\.)\s+[\w\s]+$)|(?:\s+\d{4}\s*$)|(?:\s+-\s+[\w\s]+$)",
    re.IGNORECASE,
)

_YEAR_CUTOFF_RE = re.compile(r"\s*(?:19|20)\d{2}\b.*$")

_TITLE_JUNK_CHARS_RE = re.compile("[:–,„“]")

_LEADING_ARTICLE_RE = re.compile(r"^(?:Der|Die|Das)\s+", re.IGNORECASE)

_PARENTHESIZED_ABBREVIATION_RE = re.compile(r"\(([A-ZÄÖÜ]{2,4})\)")

# Matches regional words to translate regionals ("Nordost" -> "NO")
_DIRECTION_INITIALS = {"nord": "N", "ost": "O", "süd": "S", "sued": "S", "west": "W"}

_REGION_MEISTERSCHAFT_RE = re.compile(
    # Matches regional tournament labels
    r"^((?:nord|ost|süd|sued|west)+)deutsche\s+(?:Debattier)?[Mm]eisterschaft\b",
    re.IGNORECASE,
)

# Matches abbreviated regional championships
_REGION_ABBREVIATION_RE = re.compile(r"^[NOSW]{1,3}DM$")


def _extract_tournament_name(url: str, title: str) -> str:
    """
    Extracts the clear name of the tournament from an article's headline.
    Some extractions are manually overwritten in tournament_title_replacements.json
    """
    if url in _TOURNAMENT_NAME_OVERRIDES:
        return _TOURNAMENT_NAME_OVERRIDES[url]

    # If there is an abbreviation after a tournament name, us this
    parenthesized = _parenthesized_region_abbreviation(title)
    if parenthesized:
        return parenthesized

    if _REGIONALMEISTERSCHAFTEN_RE.search(title or url):
        return "Regios"

    if title:
        out = title
    else:
        out = url.removeprefix("https://www.achteminute.de/").split("/")[1]
        out = out.replace("-", " ").title()

    match = _WINNER_PREFIX_RE.search(out)
    if match:
        out = match.group(1)

    for large_description, replacement in _TITLE_REPLACEMENTS:
        out = large_description.sub(replacement, out)

    daten_und_ergebnisse_match = _DATEN_UND_ERGEBNISSE_RE.match(out)
    if daten_und_ergebnisse_match:
        out = daten_und_ergebnisse_match.group(1)

    out = _BREAK_SUFFIX_RE.sub("", out).strip()
    out = _OVERVIEW_SUFFIX_RE.sub("", out).strip()
    out = _PREPOSITION_YEAR_SUFFIX_RE.sub("", out).strip()

    # Cut out all years from tournament names
    out = _YEAR_CUTOFF_RE.sub("", out).strip()

    # Remove characters not belonging in the Title
    out = _TITLE_JUNK_CHARS_RE.sub("", out)

    # Remove all leading articles
    out = _LEADING_ARTICLE_RE.sub("", out).strip()

    return out


def _tournament_name_for_section(section: str) -> str:
    """
    If an article contains multiple tournaments extract each segment
    seperately (happens only in regional championship articles)
    """
    if section.isupper() and " " in section:
        section = section.title()

    return _abbreviate_region_name(section) or section


def _parenthesized_region_abbreviation(text: str) -> str | None:
    """
    Finds a regional championship's abbreviation when it's already spelled
    out in parentheses
    """
    match = _PARENTHESIZED_ABBREVIATION_RE.search(text)
    if match and _REGION_ABBREVIATION_RE.match(match.group(1)):
        return match.group(1)
    return None


def _abbreviate_region_name(name: str) -> str | None:
    """
    Abbreviates a regional championship's name
    """
    name = name.strip()

    parenthesized = _parenthesized_region_abbreviation(name)
    if parenthesized:
        return parenthesized

    if _REGION_ABBREVIATION_RE.match(name.upper()):
        return name.upper()

    match = _REGION_MEISTERSCHAFT_RE.match(name)
    if not match:
        return None

    directions = match.group(1).lower()
    initials = ""
    while directions:
        for word, initial in _DIRECTION_INITIALS.items():
            if directions.startswith(word):
                initials += initial
                directions = directions[len(word) :]
                break
        else:
            return None

    return f"{initials}DM"
