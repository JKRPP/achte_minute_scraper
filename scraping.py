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
    r"(?<!\S)(Regierung|Reg|Opposition|Opp|(?:Fraktionsfreie|Freie)\s+Redner|FFR)\s*:"
    r"|(?<!\S)Es\s+jurierten\b",
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


def _blockquote_segments(blockquote) -> List[str]:
    """
    Flattens a <blockquote> into logical segments (one topic/factsheet/round
    label per segment).
    """
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
                    segments.append(current.strip())
                    current = ""
                    current_is_strong_only = True
            elif descendant.name in ("strong", "b"):
                # Split on a new highlighted spot
                if current.strip() and not current_is_strong_only:
                    segments.append(current.strip())
                    current = ""
                    current_is_strong_only = True
                br_run = 0
        if current.strip():
            segments.append(current.strip())
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


def _finalize_round(round_label: str, content: List[str]) -> Optional[Dict[str, str]]:
    """
    Turns a round's accumulated segments into a {Runde, Thema, Factsheet, Format}
    entry.
    """
    if round_label is None or not content:
        return None

    topic_index = len(content) - 1
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
        topic_index = i
        break

    topic = content[topic_index]
    factsheet_parts = content[:topic_index] + content[topic_index + 1 :]

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


def extract_topics_from_article(url: str) -> List[Dict[str, str]]:
    """
    Extracts round/topic/factsheet triples from an article page.

    Topics live inside <blockquote>, as a sequence of segments (see
    _blockquote_segments):
      - A segment starting with "Runde:" opens a new round.
      - Every segment up to (not including) the next round label belongs to
        that round, with the last one being the topic and everything before
        it forming the factsheet (see _finalize_round).
    """
    soup = download_article(url)
    date = extract_date_from_url(url)

    entries = []
    for blockquote in soup.find_all("blockquote"):
        current_round = None
        current_content: List[str] = []

        for segment in _blockquote_segments(blockquote):
            if not any(c.isalnum() for c in segment) or _SECTION_HEADER_RE.match(
                segment
            ):
                # Continue on decorative splitter
                continue

            label_match = _ROUND_LABEL_LINE_RE.match(segment)
            if label_match and (
                any(
                    word.startswith(_LABEL_STEMS)
                    for word in label_match.group(1).lower().split()
                )
                or not _is_known_round_label(label_match.group(1))
            ):
                label_match = None

            if label_match:
                if not any(_LINEUP_MARKER_RE.search(c) for c in current_content):
                    entry = _finalize_round(current_round, current_content)
                    if entry:
                        entries.append(entry)

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
                entries.append(entry)

    tournament_name = _extract_tournament_name(url)

    for entry in entries:
        entry["Link"] = url
        entry["Tournament"] = tournament_name
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
    """
    if "?" in topic:
        return "OPD"

    topic_to_match = topic.strip().replace('"', "")

    bp_pattern = r"(DH|Dieses Haus|Diese Haus|This house|TH)"
    if re.search(bp_pattern, topic_to_match, re.IGNORECASE):
        return "BP"

    opd_pattern = r"^(Sollte|Soll|Sollten|Ist)\b"
    if re.match(opd_pattern, topic_to_match, re.IGNORECASE):
        return "OPD"

    return "unbekannt"


def _extract_tournament_name(url: str) -> str:
    """
    Gets an URL and extracts the clear name of the tournament. Does not work if the tournament name is not part of the url.
    """
    out = url.removeprefix("https://www.achteminute.de/")
    out = out.split("/")[1]
    pattern_start = re.compile(
        r"(?:gewinnt|gewinnen|siegreich|wins?)[- ](?:beim|den|die|das|dem|des|der|einen?|eine[mnrs]?|d[iea]|de[mnrs]?|the)?\s*(.+)$",
        re.IGNORECASE,
    )

    match = re.search(pattern_start, out)
    if match:
        out = match.group(1)

    out = out.replace("-", " ")
    out = out.title()

    for large_description in _TOURNAMENT_TITLE_REPLACEMENTS.keys():
        out = out.replace(
            large_description, _TOURNAMENT_TITLE_REPLACEMENTS[large_description]
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
        r"\s+(?:Der|Die)\s+(?:Ergebnisse|U(?:e|ü)?berblick|U(?:e|ü)?bersicht)(?:\s+Des\s+.+)?\s*$",
        re.IGNORECASE,
    )
    out = re.sub(overview_suffix_re, "", out).strip()

    pattern_end = re.compile(
        r"(?:\s+(?:in|bei|am|im|vor|nach|aus|zu|vom|v\.)\s+[\w\s]+$)|(?:\s+\d{4}\s*$)|(?:\s+-\s+[\w\s]+$)",
        re.IGNORECASE,
    )

    out = re.sub(pattern_end, "", out).strip()

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
