"""Static data: JSON lookups from data/ and the values derived from them."""

import json
import re
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"

# Contains abbreviations (DHW -> Dieses Haus Würde etc.)
with open(_DATA_DIR / "motion_type_abbreviations.json", "r", encoding="utf-8") as f:
    _MOTION_TYPE_ABBREVIATIONS = json.load(f)

# Contains common misspellings in motions
with open(_DATA_DIR / "common_typos.json", "r", encoding="utf-8") as f:
    _COMMON_TYPOS = {typo.lower(): fix for typo, fix in json.load(f).items()}

_COMMON_TYPO_RE = re.compile(
    "|".join(rf"\b{re.escape(typo)}\b" for typo in _COMMON_TYPOS), re.IGNORECASE
)

# Manual overrides for tournament topics
with open(_DATA_DIR / "tournament_name_overrides.json", "r", encoding="utf-8") as f:
    _TOURNAMENT_NAME_OVERRIDES = json.load(f)

with open(_DATA_DIR / "tournament_title_replacements.json", "r", encoding="utf-8") as f:
    _TOURNAMENT_TITLE_REPLACEMENTS = json.load(f)

with open(_DATA_DIR / "round_translations.json", "r", encoding="utf-8") as f:
    _ROUND_TRANSLATIONS = json.load(f)

# Known labels that signify a tournament round
_KNOWN_ROUND_LABELS = {k.lower() for k in _ROUND_TRANSLATIONS} | {
    v.lower() for v in _ROUND_TRANSLATIONS.values()
}

# A numbered round label such as "VR1" or "HF 1"
_NUMBERED_LABEL_RE = re.compile(r"^([A-Za-zÀ-ÿ\-]+)\s*\d+$")

# Letter-prefixes of known numbered rounds ("VR", "HF" etc.)
_KNOWN_ROUND_PREFIXES = {
    match.group(1).lower()
    for label in _KNOWN_ROUND_LABELS
    for match in [_NUMBERED_LABEL_RE.match(label)]
    if match
}

_BP_ABBREVIATIONS = sorted(
    {
        abbr.strip(" ,.")
        for lang_abbrs in _MOTION_TYPE_ABBREVIATIONS.values()
        for abbr in lang_abbrs
    },
    key=len,
    reverse=True,
)

_BP_OPENER_RE = "|".join(re.escape(abbr) for abbr in _BP_ABBREVIATIONS)

# Phrases that open a motion and signify a specific format
_BP_MOTION_START = rf"{_BP_OPENER_RE}|Dieses Haus|Diese Haus|This house"
_OPD_MOTION_START = "Sollte|Soll|Sollten|Ist|Würdest"
