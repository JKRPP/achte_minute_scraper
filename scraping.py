import json
import re
import time
from pathlib import Path
from tqdm import tqdm
import httpx
from bs4 import BeautifulSoup, NavigableString
from datetime import datetime, timedelta
from typing import List, Optional, Dict
import pandas as pd
import pycld2 as cld2

from paths import ARTICLE_DIR, CACHE_DIR

_DATA_DIR = Path(__file__).parent / "data"

_http_client = httpx.Client(http2=True, headers={"User-Agent": "Mozilla/5.0"})

_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2

_QUOTE_CHARS = "\"'„“”‚‘’«»"

_LABEL_WORD_RE = re.compile(r"^([A-Za-zÀ-ÿ]+)\s*:?\s*")
_LABEL_STEMS = ("info", "fact", "definition", "beispiel")
_DATE_IN_URL_RE = re.compile(r"/(\d{8})/")
# Matches a year and everything after it in an extracted tournament name -
# it's already tracked separately in the "Datum" column, and whatever
# follows a year in a headline is never still part of the tournament name.
_YEAR_CUTOFF_RE = re.compile(r"\s*(?:19|20)\d{2}\b.*$")
_ROUND_LABEL_LINE_RE = re.compile(
    # The colon must not be directly followed by a lowercase letter, so
    # gender-colon notation (e.g. "Streamer:innen") in running text isn't
    # mistaken for a round label. Unlike requiring trailing whitespace,
    # this still allows a label glued directly to the next tag with no
    # whitespace at all in the source HTML (e.g. "<strong>R5:</strong><em>Info
    # text: ...</em>", which renders as "R5:Info text: ...").
    # An optional "(vorbereitet)"-style annotation may sit between the
    # label and the colon (e.g. "Runde 1 (vorbereitet): This House ...").
    r"^\(?((?:[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]*\s?){1,4}[0-9]{0,3})(?:\s*\([^)]*\))?:(?![a-zäöüß])\s*(.*)$",
    re.DOTALL,
)
_SECTION_HEADER_RE = re.compile(r"^[A-Za-zÀ-ÿ]+(?:\s[A-Za-zÀ-ÿ]+)+:$")
# Markers that only ever show up in round-lineup announcements (team
# rosters, judges), never in actual topic/factsheet content. A round whose
# content contains one of these is a lineup blurb, not a topic, and should
# be dropped rather than mining a person's name out of it as the "topic".
_LINEUP_MARKER_RE = re.compile(
    r"(?<!\S)(Regierung|Reg|Opposition|Opp|(?:Fraktionsfreie|Freie)\s+Redner|FFR"
    # Abbreviated position labels: German ER/EO/SR/SO (Eröffnende/
    # Schließende Regierung/Opposition) and BP's English OG/OO/CG/CO
    # (Opening/Closing Government/Opposition). Kept case-sensitive (even
    # though the rest of the pattern isn't) so this doesn't also match an
    # ordinary capitalized word like "So:" at the start of a sentence.
    r"|(?-i:ER|EO|SR|SO|OG|OO|CG|CO))\s*:" r"|(?<!\S)Es\s+jurierten\b",
    re.IGNORECASE,
)

# Ignore control chars for cld2
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# WordPress category ID for "Turniere" (tournaments), resolved via
# GET /wp-json/wp/v2/categories?search=Turniere - the only category whose
# articles ever contain topics.
_TURNIERE_CATEGORY_ID = 46


with open(_DATA_DIR / "tournament_title_replacements.json", "r", encoding="utf-8") as f:
    _TOURNAMENT_TITLE_REPLACEMENTS = json.load(f)

# Known BP motion-opener abbreviations (e.g. "DHG" for "Dieses Haus
# glaubt"), reused from motion_type_abbreviations.json so the format
# detector in _extract_format_from_topic recognizes exactly the same set
# topic_merger.py already knows how to expand - rather than a bare "DH"/
# "TH" that would also match as a false-positive substring inside an
# unrelated word (e.g. "TH" inside "The").
with open(_DATA_DIR / "motion_type_abbreviations.json", "r", encoding="utf-8") as f:
    _MOTION_TYPE_ABBREVIATIONS = json.load(f)
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

# A segment "looks like a topic" if it ends in a question (OPD-style) or
# opens with a known motion phrasing (BP-style) - used to tell a round's
# real topic apart from trailing narrative prose in "story" articles (see
# _finalize_round).
_TOPIC_LIKE_RE = re.compile(
    rf"\?\s*$|^(?:{_BP_OPENER_RE}|Dieses Haus|Diese Haus|This house)\b"
    r"|^(?:Sollte|Soll|Sollten|Ist|Würdest)\b",
    re.IGNORECASE,
)

# Common typos (e.g. "Diese Haus" -> "Dieses Haus") found in topics/
# factsheets, corrected before format/language detection so they aren't
# silently defeated by a misspelled key phrase.
with open(_DATA_DIR / "common_typos.json", "r", encoding="utf-8") as f:
    _COMMON_TYPOS = {typo.lower(): fix for typo, fix in json.load(f).items()}
_COMMON_TYPO_RE = re.compile(
    "|".join(rf"\b{re.escape(typo)}\b" for typo in _COMMON_TYPOS), re.IGNORECASE
)

# Manual overrides for articles whose headline phrasing doesn't fit any
# general pattern (e.g. "X, Y und Z sind die Sieger der ..."). Keyed by the
# full article URL, since the phrasing that defeats the heuristic is
# specific to that one headline rather than a reusable pattern.
with open(_DATA_DIR / "tournament_name_overrides.json", "r", encoding="utf-8") as f:
    _TOURNAMENT_NAME_OVERRIDES = json.load(f)

# Maps a German cardinal-direction word to the initial used in a regional
# championship's abbreviation (e.g. "nordost" -> "NO", so "Nordostdeutsche
# Debattiermeisterschaft" abbreviates to "NODM").
_DIRECTION_INITIALS = {"nord": "N", "ost": "O", "süd": "S", "sued": "S", "west": "W"}
_REGION_MEISTERSCHAFT_RE = re.compile(
    # Not anchored at the end - a section heading often trails the region
    # name with a host city (e.g. "Süddeutsche Debattiermeisterschaft,
    # Tübingen"), which isn't part of the name itself.
    r"^((?:nord|ost|süd|sued|west)+)deutsche\s+(?:Debattier)?[Mm]eisterschaft\b",
    re.IGNORECASE,
)
# A regional championship's abbreviation is always its compass initials
# followed by "DM" (e.g. "NODM", "WDM") - matches an abbreviation some
# early "Regionalmeisterschaften" roundup articles already use in their
# intro sentence (e.g. "Alle weiteren Themen der NODM in der Übersicht:").
_REGION_ABBREVIATION_RE = re.compile(r"^[NOSW]{1,3}DM$")

with open(_DATA_DIR / "round_translations.json", "r", encoding="utf-8") as f:
    _ROUND_TRANSLATIONS = json.load(f)

# Known-legitimate round labels (both raw variants and their canonical
# translations), used to reject look-alike "Word:" segments that aren't
# actually round labels.
_KNOWN_ROUND_LABELS = {k.lower() for k in _ROUND_TRANSLATIONS} | {
    v.lower() for v in _ROUND_TRANSLATIONS.values()
}
# Letter-prefixes of known numbered rounds (e.g. "VR" from "VR1", "HF" from
# "HF 1"), so numbers beyond what's literally listed (e.g. "VR12") still
# match.
_KNOWN_ROUND_PREFIXES = {
    match.group(1).lower()
    for label in _KNOWN_ROUND_LABELS
    for match in [re.match(r"^([A-Za-zÀ-ÿ\-]+)\s*\d+$", label)]
    if match
}


def _is_known_round_label(label: str) -> bool:
    """Checks whether a matched label is a legitimate round label."""
    normalized = re.sub(r"\s+", " ", label).strip().lower()
    if normalized in _KNOWN_ROUND_LABELS:
        return True
    prefix_match = re.match(r"^([A-Za-zÀ-ÿ\-]+)\s*\d+$", normalized)
    return bool(prefix_match and prefix_match.group(1) in _KNOWN_ROUND_PREFIXES)


_EMBEDDED_ROUND_LABEL_RE = re.compile(
    r"(?:^|(?<=\s))\(?((?:[A-ZÄÖÜ][A-Za-zÄÖÜäöüß\-]*\s?){1,4}[0-9]{0,3})(?:\s*\([^)]*\))?:(?![a-zäöüß])"
)


def _split_multi_round_segment(segment: str) -> List[str]:
    """
    Splits a segment holding several "Runde N: ..." entries glued together
    by a single <br> (rather than the blank-line-style double <br> that
    normally separates segments - see _blockquote_segments) into one
    segment per round.
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


def _match_round_label(segment: str):
    """
    Matches a round-label line, peeling off an unrecognized leading label
    and retrying against what follows it. Needed for e.g. an inline
    sub-tournament heading like "Regio Marburg:" that shares one <p> (and
    therefore one segment) with the real round label right after it via a
    <br> - without this, the whole segment (real label included) would be
    rejected wholesale as belonging to the bogus "Regio Marburg" label.
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


def _get(url: str) -> httpx.Response:
    """
    GETs a URL, retrying on transient connection failures (e.g. "Server
    disconnected") with a short backoff, since achteminute.de occasionally
    drops connections under no fault of the request itself.
    """
    _http_client.cookies.clear()
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = _http_client.get(url)
            response.raise_for_status()
            return response
        except httpx.TransportError:
            if attempt == _MAX_RETRIES:
                raise
            time.sleep(_RETRY_BACKOFF_SECONDS * attempt)


def get_all_article_links(
    start_year: int = 2026,
    start_month: int = 1,
    end_year: Optional[int] = None,
    end_month: Optional[int] = None,
) -> List[str]:
    """
    Fetches all article links published in the given date range via the
    WordPress REST API, filtered to the "Turniere" (tournament) category.

    Args:
        start_year: The year to start from (default: 2026).
        start_month: The month to start from (default: 1 for January).
        end_year: The year to end at (inclusive). If None, uses the current month.
        end_month: The month to end at (inclusive). If None, uses the current month.

    Returns:
        A combined list of all article URLs from the specified range.
    """
    if end_year is None or end_month is None:
        today = datetime.now()
        end_year = today.year
        end_month = today.month

    start_date = datetime(start_year, start_month, 1)
    end_date = (
        datetime(end_year + 1, 1, 1)
        if end_month == 12
        else datetime(end_year, end_month + 1, 1)
    )
    # Bounds are exclusive, nudged by one second to prevent overlap.
    after = (start_date - timedelta(seconds=1)).isoformat()
    before = end_date.isoformat()

    print(
        f"Fetching tournament article links from {start_date:%B %Y} "
        f"to {datetime(end_year, end_month, 1):%B %Y}..."
    )

    article_links = []
    page = 1
    while True:
        try:
            response = _get(
                "https://www.achteminute.de/wp-json/wp/v2/posts"
                f"?categories={_TURNIERE_CATEGORY_ID}&after={after}&before={before}"
                f"&per_page=100&page={page}&_fields=link"
            )
        except httpx.HTTPError as e:
            # WP returns 400 once "page" exceeds the available page count.
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 400:
                break
            print(f"Error fetching article links (page {page}): {e}")
            break

        posts = response.json()
        if not posts:
            break

        article_links.extend(post["link"] for post in posts)
        if len(posts) < 100:
            break
        page += 1

    return article_links


def extract_date_from_url(url: str) -> Optional[str]:
    """Article URLs encode their publish date as /YYYYMMDD/ (e.g. /20260521/...)."""
    match = _DATE_IN_URL_RE.search(url)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
    except ValueError:
        return None


def _linkify_anchors(blockquote) -> None:
    """
    Replaces <a href="..."> tags with a "[text](href)" markdown-style
    string, so links formatted as words (e.g. "hier") survive being
    flattened to plain text.
    """
    for a in blockquote.find_all("a"):
        href = a.get("href", "").strip()
        text = a.get_text().strip()
        a.replace_with(f"[{text}]({href})" if href else text)


def _blockquote_segments(blockquote) -> List[str]:
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
        # split across different bold-ish tags (e.g. "<b>VR</b><strong>7</strong>:").
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
                if br_run >= 2 and current.strip():
                    segments.extend(_split_multi_round_segment(current.strip()))
                    current = ""
                    current_is_strong_only = True
            elif descendant.name in ("strong", "b"):
                # Split on a new highlighted spot
                if current.strip() and not current_is_strong_only:
                    segments.extend(_split_multi_round_segment(current.strip()))
                    current = ""
                    current_is_strong_only = True
                br_run = 0
        if current.strip():
            segments.extend(_split_multi_round_segment(current.strip()))
    return segments


def _strip_quotes(text: str) -> str:
    """Strips a single leading/trailing quote mark, if both are present."""
    if len(text) >= 2 and text[0] in _QUOTE_CHARS and text[-1] in _QUOTE_CHARS:
        text = text[1:-1].strip()
    return text


def _normalize_whitespace(text: str) -> str:
    """Collapses internal whitespace (e.g. single-<br/> line wraps) to single spaces."""
    return re.sub(r"\s+", " ", text).strip()


def _split_labelled_topic(text: str) -> tuple[str, str]:
    """
    Splits topics that start with "Factsheet:" or similar
    into topic (last sentence) and factsheet (everything else)
    """
    if "\n" in text:
        prefix, _, last = text.rpartition("\n")
        if prefix.strip() and last.strip():
            return prefix.strip(), last.strip()

    # No newline to split on: fall back to the last sentence boundary
    # (a '.', '?' or '!' followed by whitespace + a capital letter, or by
    # end of string).
    matches = list(re.finditer(r"[.?!]+(?=\s+[A-ZÄÖÜ]|\s*$)", text))
    for match in reversed(matches):
        prefix, last = text[: match.end()], text[match.end() :]
        if prefix.strip() and last.strip():
            return prefix.strip(), last.strip()

    return "", text


_TRAILING_LABEL_RE = re.compile(
    r"(?<!\S)(Fact(?:sheet)?|Info(?:slide)?|Definition)\s*:", re.IGNORECASE
)


def _split_trailing_factsheet(text: str) -> tuple[str, str]:
    """
    Moves a trailing factsheet from the topic to the factsheet.
    """
    match = _TRAILING_LABEL_RE.search(text)
    if not match or match.start() == 0:
        return text, ""

    topic = text[: match.start()].strip()
    factsheet = text[match.start() :].strip()
    if not topic or not factsheet:
        return text, ""

    return topic, factsheet


def _split_leading_parenthetical(
    text: str, require_label: bool = True
) -> tuple[str, str]:
    """
    If there is no previous factsheet (require_label = True),
    moves a leading parenthesis into the factsheet.
    """
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

    if require_label:
        # "(inkl. Factsheet)" / "(inkl. Info-Slide: ...)" style
        # parentheticals lead with "inkl." before the actual label word.
        inner_for_label_check = re.sub(r"^inkl\.?\s*", "", inner, flags=re.IGNORECASE)
        inner_label_match = _LABEL_WORD_RE.match(inner_for_label_check)
        is_factsheet_like = bool(
            inner_label_match
            and inner_label_match.group(1).lower().startswith(_LABEL_STEMS)
        )
        if not is_factsheet_like:
            return "", text

    remainder = stripped[close_index + 1 :].strip()
    if not remainder:
        return "", text

    return inner, remainder


def _looks_like_topic(text: str) -> bool:
    """See _TOPIC_LIKE_RE."""
    return bool(_TOPIC_LIKE_RE.search(text.strip()))


def _fix_common_typos(text: str) -> str:
    """Corrects known common typos (see common_typos.json) in a topic/factsheet."""
    if not text:
        return text
    return _COMMON_TYPO_RE.sub(lambda m: _COMMON_TYPOS[m.group(0).lower()], text)


def _finalize_round(round_label: str, content: List[str]) -> Optional[Dict[str, str]]:
    """
    Turns a round's accumulated segments into a {Runde, Thema, Factsheet, Format}
    entry.
    """
    if round_label is None or not content:
        return None

    topic_index = None
    fallback_topic_index = None
    # Segments that get scanned past while looking for the topic (see
    # below) but that neither look like a topic nor like recognized
    # factsheet content - e.g. a "story" article's narrative prose bridging
    # one round's topic to the next - shouldn't end up glued into the
    # factsheet either, so they're dropped entirely.
    dropped_indices = set()
    for i in range(len(content) - 1, -1, -1):
        label_match = _LABEL_WORD_RE.match(content[i])
        is_labeled = bool(
            label_match and label_match.group(1).lower().startswith(_LABEL_STEMS)
        )
        # Bullet-style continuation lines (e.g. "– stärkere Einbeziehung ...")
        # are always factsheet list items trailing an "Info:"/"Fact:"
        # paragraph, never a round's topic question, so skip them too.
        is_bullet_continuation = content[i].lstrip().startswith(("-", "–", "—", "•"))
        # A segment entirely wrapped in parentheses is a clarifying aside
        # trailing the real topic (e.g. "(Es sei anzunehmen dass ...)"),
        # not the topic itself.
        stripped = content[i].strip()
        is_parenthetical_aside = stripped.startswith("(") and stripped.endswith(")")
        # A footnote trailing the topic (e.g. "*Including but not limited
        # to: ..." or "[2] e.g of target-based regulations: ...") explains
        # a marker (*, [1]) referenced from within an earlier segment, so
        # it's factsheet content, never the topic itself.
        is_footnote = bool(re.match(r"^(?:\*+|\[\d+\])", stripped))
        if (
            is_labeled
            or is_bullet_continuation
            or is_parenthetical_aside
            or is_footnote
        ):
            continue

        if fallback_topic_index is None:
            fallback_topic_index = i
        if _looks_like_topic(content[i]):
            topic_index = i
            break
        dropped_indices.add(i)

    if topic_index is None:
        # Nothing scanned looked like a topic (shouldn't normally happen) -
        # fall back to the previous behavior of just using the last
        # non-excluded segment, rather than dropping every candidate.
        topic_index = (
            fallback_topic_index
            if fallback_topic_index is not None
            else len(content) - 1
        )
        dropped_indices.discard(topic_index)

    topic = content[topic_index]
    factsheet_parts = [
        part
        for idx, part in enumerate(content)
        if idx != topic_index and idx not in dropped_indices
    ]

    topic_label_match = _LABEL_WORD_RE.match(topic)
    if topic_label_match and topic_label_match.group(1).lower().startswith(
        _LABEL_STEMS
    ):
        inline_factsheet, topic = _split_labelled_topic(topic)
        if inline_factsheet:
            factsheet_parts.append(inline_factsheet)
    else:
        # The topic may come first, with a factsheet/infoslide label
        # appearing later in the same segment (e.g. "Sollten ...?
        # Factsheet: ...").
        new_topic, trailing_factsheet = _split_trailing_factsheet(topic)
        if trailing_factsheet:
            topic = new_topic
            factsheet_parts.append(trailing_factsheet)

    # If the round has no other factsheet content, any leading parenthetical
    # is by definition that infoslide, labelled or not.
    leading_parenthetical, topic = _split_leading_parenthetical(
        topic, require_label=bool(factsheet_parts)
    )
    if leading_parenthetical:
        factsheet_parts.append(leading_parenthetical)

    stripped_parts = []
    for part in factsheet_parts:
        part = re.sub(r"^inkl\.?\s*", "", part, flags=re.IGNORECASE)
        label_match = _LABEL_WORD_RE.match(part)
        if label_match and label_match.group(1).lower().startswith(_LABEL_STEMS):
            # Cut at the label's colon rather than just the first word, so
            # multi-word labels (e.g. "info slide:") are fully removed.
            colon_index = part.find(":", 0, 30)
            cut = colon_index + 1 if colon_index != -1 else label_match.end()
            part = part[cut:].strip()
        stripped_parts.append(part)

    factsheet = _normalize_whitespace(
        _strip_quotes(" ".join(part for part in stripped_parts if part).strip())
    )

    # Fix common typos (e.g. "Diese Haus" -> "Dieses Haus") before anything
    # downstream matches against the topic/factsheet text - format and
    # language detection both key off exact phrases, and a typo silently
    # defeats them.
    topic = _fix_common_typos(topic)
    factsheet = _fix_common_typos(factsheet)

    topic_format = _extract_format_from_topic(topic)

    if topic_format == "unbekannt":
        factsheet_format = _extract_format_from_topic(factsheet)
        if factsheet_format != "unbekannt":
            topic_format = factsheet_format
            topic, factsheet = factsheet, topic

    full_text = f"{factsheet} {topic}".strip()
    language = _detect_language(full_text)

    return {
        "Runde": round_label,
        "Thema": _normalize_whitespace(_strip_quotes(topic)),
        "Factsheet": factsheet,
        "Sprache": language,
    }


def _extract_article_body(full_soup: BeautifulSoup) -> BeautifulSoup:
    """
    Trims a full achteminute.de page down to the article itself (title,
    date/author/category, body, tags).
    """
    post = full_soup.find("div", class_="post")
    if post is None:
        return full_soup

    for button in post.find_all(class_="printfriendly"):
        button.decompose()

    tags = post.find_next_sibling("small")

    trimmed = BeautifulSoup("", "html.parser")
    trimmed.append(post.extract())
    if tags is not None:
        trimmed.append(tags.extract())

    return trimmed


def _extract_title(soup: BeautifulSoup) -> str:
    """
    Gets the article's headline (the first <h2> in the trimmed article
    body), which retains real casing, umlauts and punctuation - unlike the
    URL slug, which is ASCII-folded and hyphen-joined.
    """
    heading = soup.find("h2")
    return _normalize_whitespace(heading.get_text()) if heading else ""


def download_article(url: str, overwrite=False):
    file_path = ARTICLE_DIR / (
        url.removeprefix("https://www.achteminute.de/")
        .replace("/", "_")
        .removesuffix("_")
    )

    if file_path.exists() and not overwrite:
        html_string = file_path.read_text(encoding="utf-8")
        return BeautifulSoup(html_string, "html.parser")

    try:
        response = _get(url)
    except httpx.HTTPError as e:
        print(f"Error fetching {url}: {e}")
        return []

    soup = _extract_article_body(BeautifulSoup(response.content, "html.parser"))
    ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
    file_path.write_text(str(soup), encoding="utf-8")

    return soup


# A standalone paragraph naming just a host city/region (e.g. "Ingolstadt"),
# used by older articles (pre-2014ish) to separate multiple regional
# tournaments covered in one post, before they got grouped under an <h3>
# with the region's actual championship name (e.g. "Norddeutsche
# Debattiermeisterschaft"). Recognized as a <p> whose entire text is a
# single <strong> run, isn't a content-type label like "Teambreak:" (which
# also renders as a lone bold paragraph), and is short enough to be a name
# rather than a sentence.
_SECTION_CITY_PARAGRAPH_MAX_LEN = 40

# Matches the lead-in sentence used by some early roundup articles instead
# of a proper heading, e.g. "Alle weiteren Themen der NODM in der
# Übersicht:" or "... der WDM in der Übersicht:".
_SECTION_ABBREVIATION_INTRO_RE = re.compile(
    r"Themen\s+de[rs]\s+([A-ZÄÖÜ]{2,6})\s+in\s+der\s+(?:Übersicht|Ubersicht)",
    re.IGNORECASE,
)

# Recurring result/jury-related labels that (like a real section heading)
# can render as a single standalone bold paragraph, e.g. "Jurierendenbreak"
# with no trailing colon - excluded so they aren't mistaken for a section.
_SECTION_HEADING_BLOCKLIST_RE = re.compile(
    r"break|jur(?:y|ier|or)|tabmaster|casefile|equity|rednerinnen|top\s*\d",
    re.IGNORECASE,
)


def _section_headings_by_blockquote(soup: BeautifulSoup) -> Dict[int, str]:
    """
    Maps each <blockquote> (by id()) in the article to the name of the
    tournament section it belongs to, for articles covering multiple
    regional tournaments in a single post. Returns an empty mapping for
    ordinary single-tournament articles (nothing before their first, and
    only, blockquote looks like a section heading).
    """
    sections: Dict[int, str] = {}
    current: Optional[str] = None

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
        else:  # blockquote
            if current is not None:
                sections[id(tag)] = current

    # A single-tournament article can still contain one stray paragraph
    # that looks like a section heading (e.g. an unusually-phrased result
    # label). Only trust the detected sections once they actually
    # distinguish 2+ tournaments - otherwise fall back to the article-level
    # tournament name for every entry.
    if len(set(sections.values())) < 2:
        return {}

    return sections


def _parenthesized_region_abbreviation(text: str) -> Optional[str]:
    """
    Finds a regional championship's abbreviation when it's already spelled
    out in parentheses somewhere in text (e.g. "Nordostdeutsche
    Meisterschaft (NODM), Jena" or "Westdeutsche Meisterschaft (WDM),
    Bonn"), regardless of what surrounds it.
    """
    match = re.search(r"\(([A-ZÄÖÜ]{2,4})\)", text)
    if match and _REGION_ABBREVIATION_RE.match(match.group(1)):
        return match.group(1)
    return None


def _abbreviate_region_name(name: str) -> Optional[str]:
    """
    Abbreviates a regional championship's name (e.g. "Nordostdeutsche
    Debattiermeisterschaft" or already-abbreviated "NODM") to its canonical
    form, or returns None if name isn't a regional-championship name at all
    (e.g. a host city or a one-off tournament name).
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


def _tournament_name_for_section(section: str) -> str:
    """
    Builds a concrete tournament name for one section of a multi-tournament
    article (see _section_headings_by_blockquote). Sections naming a
    regional championship (spelled out or already abbreviated) are
    abbreviated (e.g. "NDM"); sections that are just a host city (older
    articles) are phrased as a regional championship instead. The year
    isn't included - it's already tracked separately in the "Datum" column.
    """
    if section.isupper() and " " in section:
        section = section.title()

    abbreviation = _abbreviate_region_name(section)
    if abbreviation:
        return abbreviation

    return section


def extract_topics_from_article(url: str) -> List[Dict[str, str]]:
    """
    Extracts round/topic/factsheet triples from an article page.

    Topics live inside <blockquote>, as a sequence of segments (see
    _blockquote_segments):
      - A segment starting with "Runde:" opens a new round.
      - Every segment up to (not including) the next round label belongs to
        that round, with the last one being the topic and everything before
        it forming the factsheet (see _finalize_round).

    Some articles (e.g. the yearly "Regionalmeisterschaften" roundup) cover
    several regional tournaments in one post; entries are attributed to the
    specific one they came from rather than the article as a whole (see
    _section_headings_by_blockquote).
    """
    soup = download_article(url)
    date = extract_date_from_url(url)
    sections = _section_headings_by_blockquote(soup)

    entries = []
    for blockquote in soup.find_all("blockquote"):
        section = sections.get(id(blockquote))
        current_round = None
        current_content: List[str] = []
        blockquote_entries: List[Dict[str, str]] = []

        for segment in _blockquote_segments(blockquote):
            if not any(c.isalnum() for c in segment) or _SECTION_HEADER_RE.match(
                segment
            ):
                # Continue on decorative splitter
                continue

            label_match = _match_round_label(segment)

            if label_match:
                if not any(_LINEUP_MARKER_RE.search(c) for c in current_content):
                    entry = _finalize_round(current_round, current_content)
                    if entry:
                        blockquote_entries.append(entry)

                current_round = label_match.group(1).strip()
                remainder = label_match.group(2).strip()
                if segment.startswith("(") and remainder.endswith(")"):
                    remainder = remainder[:-1].strip()
                current_content = [remainder] if remainder else []
            else:
                if current_round is None:
                    continue
                current_content.append(segment)

        if not any(_LINEUP_MARKER_RE.search(c) for c in current_content):
            entry = _finalize_round(current_round, current_content)
            if entry:
                blockquote_entries.append(entry)

        for entry in blockquote_entries:
            entry["_section"] = section
        entries.extend(blockquote_entries)

    tournament_name = _extract_tournament_name(url, _extract_title(soup))

    for entry in entries:
        section = entry.pop("_section", None)
        entry["Link"] = url
        entry["Tournament"] = (
            _tournament_name_for_section(section) if section else tournament_name
        )
        entry["Datum"] = date
        entry["Format"] = _extract_format_from_topic(entry["Thema"])

    return entries


def _detect_language(input: str) -> str:
    """
    Detects the language of a given string using Googles CLD2 model.
    """
    clear_german_pattern = (
        r"(DH|Dieses Haus|begrüßt|bedauert|bereut|würde|Würde|Sollten)"
    )
    if re.search(clear_german_pattern, input):
        return "GERMAN"

    clear_english_pattern = (
        r"(This house|This House|regrets|supports|would|Would|prefers)"
    )
    if re.search(clear_english_pattern, input):
        return "ENGLISH"

    clean_input = _CONTROL_CHAR_RE.sub("", input)
    is_reliable, text_bytes, details = cld2.detect(clean_input, hintLanguage="de")
    return details[0][0] if details else "unknown"


def _extract_format_from_topic(topic: str) -> str:
    """
    Classifies a topic into either BP or OPD based on its topic string.

    Checked before the "?" -> OPD check below, since a BP motion can carry
    a rhetorical/flavor-text question before its actual "Dieses Haus..."
    clause (e.g. "The West is the best? Dieses Haus würde...").
    """
    topic_to_match = topic.strip().replace('"', "")

    # Word-bounded, and restricted to the known DH.../TH... abbreviations
    # (see _BP_ABBREVIATIONS), so this only matches an actual abbreviated
    # motion opener - not a bare "TH"/"DH" substring inside an unrelated
    # word (e.g. "TH" inside a quoted English phrase like „For The Plot"),
    # while still matching a suffixed form like "DHG" or "THW".
    bp_pattern = rf"\b(?:{_BP_OPENER_RE}|Dieses Haus|Diese Haus|This house)\b"
    if re.search(bp_pattern, topic_to_match, re.IGNORECASE):
        return "BP"

    if "?" in topic:
        return "OPD"

    # Only matched at the very start, or right after a sentence-ending
    # punctuation mark, so a leading flavor-text clause (e.g. "In eurem
    # Leben hat sich ... verändert (...): Sollte man ...") doesn't hide the
    # real motion opener - but common words like "Ist" still can't match
    # arbitrarily mid-sentence, which an unanchored search would allow.
    opd_pattern = r"(?:^|[:.!?]\s*)(?:Sollte|Soll|Sollten|Ist|Würdest)\b"
    if re.search(opd_pattern, topic_to_match, re.IGNORECASE):
        return "OPD"

    return "unbekannt"


def _extract_tournament_name(url: str, title: str = "") -> str:
    """
    Extracts the clear name of the tournament from an article's headline
    (falling back to the URL slug if no headline was available, e.g. for
    stale cached articles). Explicit per-URL overrides take precedence,
    since some headlines phrase the result in ways too varied to
    generalize into a regex (see tournament_name_overrides.json).
    """
    if url in _TOURNAMENT_NAME_OVERRIDES:
        return _TOURNAMENT_NAME_OVERRIDES[url]

    # A title that already spells out its own abbreviation in parentheses
    # (e.g. "Nordostdeutsche Meisterschaft (NODM)" or "Westdeutsche
    # Meisterschaft (WDM), Bonn") tells us exactly what to call it - no
    # need to run the general heuristics below at all.
    parenthesized = _parenthesized_region_abbreviation(title or "")
    if parenthesized:
        return parenthesized

    # Yearly "Regionalmeisterschaften" roundups cover several regional
    # tournaments in one article (see _section_headings_by_blockquote,
    # which names each entry after its specific region); this article-level
    # name is only ever used as a fallback for an entry that couldn't be
    # matched to a section, so it just needs to identify the roundup, not
    # any one region.
    if re.search(r"Regionalmeisterschaften?", title or url, re.IGNORECASE):
        return "Regios"

    if title:
        out = title
    else:
        out = url.removeprefix("https://www.achteminute.de/").split("/")[1]
        out = out.replace("-", " ").title()

    pattern_start = re.compile(
        r"(?:gewinnt|gewinnen|siegreich|wins|triumphieren|triumphiert|Sieger|siegt?)[- ](?:beim|den|die|das|dem|des|der|einen?|eine[mnrs]?|d[iea]|de[mnrs]?|the)?\s*(.+)$",
        re.IGNORECASE,
    )

    match = re.search(pattern_start, out)
    if match:
        out = match.group(1)

    for large_description, replacement in _TOURNAMENT_TITLE_REPLACEMENTS.items():
        out = re.sub(
            re.escape(large_description), replacement, out, flags=re.IGNORECASE
        )

    daten_und_ergebnisse_match = re.match(
        r"^(?:Die\s+)?(.+?)\s+Daten\s+Und\s+Ergebnisse$", out, re.IGNORECASE
    )
    if daten_und_ergebnisse_match:
        out = daten_und_ergebnisse_match.group(1)

    break_suffix_re = re.compile(
        r"\s+(?:Der|Die)?\s*Breaks?"
        r"(?:\s+Und\s+Halbfinals?)?"
        r"(?:\s+Ins\s+(?:Viertelfinale|Halbfinale|Finale|Achtelfinale))?"
        r"(?:\s+\d+)?\s*$",
        re.IGNORECASE,
    )
    out = re.sub(break_suffix_re, "", out).strip()

    overview_suffix_re = re.compile(
        r"\s+(?:Der|Die|Im)?\s*(?:Ergebnisse|U(?:e|ü)?berblick|U(?:e|ü)?bersicht)(?:\s+Des\s+.+)?\s*$",
        re.IGNORECASE,
    )
    out = re.sub(overview_suffix_re, "", out).strip()

    pattern_end = re.compile(
        r"(?:\s+(?:in|bei|beim|am|im|vor|nach|aus|zu|vom|v\.)\s+[\w\s]+$)|(?:\s+\d{4}\s*$)|(?:\s+-\s+[\w\s]+$)",
        re.IGNORECASE,
    )

    out = re.sub(pattern_end, "", out).strip()

    # A year is never actually part of the tournament's name in any article
    # we've seen - it's already tracked separately in the "Datum" column -
    # so drop it and everything that follows it (e.g. "... 2013: Übersicht
    # Vorrunden und Break" -> "...").
    out = _YEAR_CUTOFF_RE.sub("", out).strip()

    # Remove characters not belonging in the Title
    out = re.sub("[:–,„“]", "", out)

    # A leading definite article isn't part of the tournament's name either
    # (e.g. "Der Bodden-Cup" -> "Bodden-Cup", "Das Frauenturnier" ->
    # "Frauenturnier").
    out = re.sub(r"^(?:Der|Die|Das)\s+", "", out, flags=re.IGNORECASE).strip()

    return out


def extract_topics_for_links(
    links: List[str], show_progress: bool = False
) -> pd.DataFrame:
    """
    Extracts topics for a list of article links into a single DataFrame,
    skipping (and logging) any article that fails to extract instead of
    aborting the whole batch.
    """
    all_topics = []
    for link in tqdm(links) if show_progress else links:
        try:
            all_topics.extend(extract_topics_from_article(link))
        except Exception as e:
            print(
                f"WARNING: Failed to get topics from {link}: {e!r}. Skipping article."
            )

    return pd.DataFrame(all_topics)


def initial_generation(starting_year=2013, force_regenerate=False, verbose=False):
    first_year = starting_year
    last_year = datetime.now().year

    current_year = first_year

    while current_year <= last_year:
        print(f"Getting topics from {current_year}")
        if (CACHE_DIR / f"topics_{current_year}.csv").exists() and not force_regenerate:
            print(
                f"File topics_{current_year}.csv already exists. Skipping file in initial generation."
            )
            current_year += 1
            continue
        all_links = get_all_article_links(
            start_year=current_year, start_month=1, end_year=current_year, end_month=12
        )
        topic_df = extract_topics_for_links(all_links, show_progress=True)
        topic_df.to_csv(CACHE_DIR / f"topics_{current_year}.csv", index=False)
        current_year += 1


if __name__ == "__main__":
    initial_generation(force_regenerate=True)
