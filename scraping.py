import re
import time
from tqdm import tqdm
import httpx
from bs4 import BeautifulSoup, NavigableString
from datetime import datetime
from typing import List, Optional, Dict
import pandas as pd
import os

from paths import ARTICLE_DIR, CACHE_DIR

_http_client = httpx.Client(http2=True, headers={"User-Agent": "Mozilla/5.0"})

_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2

_QUOTE_CHARS = "\"'„“”‚‘’«»"

_LABEL_WORD_RE = re.compile(r"^([A-Za-zÀ-ÿ]+)\s*:?\s*")
_LABEL_STEMS = ("info", "fact", "definition")
_DATE_IN_URL_RE = re.compile(r"/(\d{8})/")
_ROUND_LABEL_LINE_RE = re.compile(
    r"^\(?([A-Za-zÄÖÜäöüß\-]{1,25}\s?[0-9]{0,3}):\s*(.*)$", re.DOTALL
)
_SECTION_HEADER_RE = re.compile(r"^[A-Za-zÀ-ÿ]+(?:\s[A-Za-zÀ-ÿ]+)+:$")

_TOURNAMENT_TITLE_REPLACEMENTS = {
    "Campus Debatte": "CD",
    "Zeit Debatte": "ZD",
    "Deutschsprachige Debattiermeisterschaft": "DDM",
}


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


def get_article_links_from_month(year: int, month: int) -> List[str]:
    """
    Fetches all article links from a given month's archive page on achteminute.de.

    Args:
        year: The year (e.g., 2026)
        month: The month (e.g., 7 for July)

    Returns:
        A list of full URLs to individual articles.
    """
    url = f"https://www.achteminute.de/{year}/{month:02d}/"
    try:
        response = _get(url)
    except httpx.HTTPError as e:
        print(f"Error fetching {url}: {e}")
        return []

    soup = BeautifulSoup(response.content, "html.parser")
    article_pattern = re.compile(
        rf"^https://www\.achteminute\.de/{year}{month:02d}\d{{2}}/.+/$"
    )

    article_links = []
    for a_tag in soup.find_all("a", href=True, rel="bookmark"):
        href = a_tag["href"]
        if not article_pattern.match(href) or href in article_links:
            continue

        # Only tournament articles ("Turniere" category) ever contain
        # topics, and the category is already shown on the archive page
        # itself, so we can skip downloading every other article entirely.
        post = a_tag.find_parent("div", class_="post_archive")
        date_div = post.find("div", class_="post_archive_date") if post else None
        categories = (
            {c.get_text(strip=True) for c in date_div.find_all("a", rel="category tag")}
            if date_div
            else set()
        )
        if "Turniere" not in categories:
            continue

        article_links.append(href)

    return article_links


def get_all_article_links(
    start_year: int = 2026,
    start_month: int = 1,
    end_year: Optional[int] = None,
    end_month: Optional[int] = None,
) -> List[str]:
    """
    Iterates through a range of months and collects all article links.

    Args:
        start_year: The year to start from (default: 2026).
        start_month: The month to start from (default: 1 for January).
        end_year: The year to end at (inclusive). If None, uses the current month.
        end_month: The month to end at (inclusive). If None, uses the current month.

    Returns:
        A combined list of all article URLs from the specified range.
    """
    all_links = []

    if end_year is None or end_month is None:
        today = datetime.now()
        end_year = today.year
        end_month = today.month

    current_date = datetime(start_year, start_month, 1)
    end_date = datetime(end_year, end_month, 1)

    while current_date <= end_date:
        print(f"Fetching links for {current_date.strftime('%B %Y')}...")
        month_links = get_article_links_from_month(
            current_date.year, current_date.month
        )
        all_links.extend(month_links)

        if current_date.month == 12:
            current_date = datetime(current_date.year + 1, 1, 1)
        else:
            current_date = datetime(current_date.year, current_date.month + 1, 1)

    return all_links


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
    for p in blockquote.find_all("p"):
        current = ""
        br_run = 0
        for descendant in p.descendants:
            if isinstance(descendant, NavigableString):
                current += str(descendant)
                if str(descendant).strip():
                    br_run = 0
            elif descendant.name == "br":
                br_run += 1
                if br_run >= 2 and current.strip():
                    segments.append(current.strip())
                    current = ""
            elif descendant.name == "strong":
                # A <strong> tag always opens a new round label, even when
                # it's embedded mid-paragraph alongside earlier content
                # (rather than in its own <p>), so force a split here too.
                if current.strip():
                    segments.append(current.strip())
                    current = ""
                br_run = 0
        if current.strip():
            segments.append(current.strip())
    return segments


def _strip_quotes(text: str) -> str:
    """Strips a single leading/trailing quote mark, if both are present."""
    if len(text) >= 2 and text[0] in _QUOTE_CHARS and text[-1] in _QUOTE_CHARS:
        text = text[1:-1].strip()
    return text


def _finalize_round(round_label: str, content: List[str]) -> Optional[Dict[str, str]]:
    """
    Turns a round's accumulated segments into a {Runde, Thema, Factsheet}
    entry.
    """
    if round_label is None or not content:
        return None

    topic_index = len(content) - 1
    for i in range(len(content) - 1, -1, -1):
        label_match = _LABEL_WORD_RE.match(content[i])
        if label_match and label_match.group(1).lower().startswith(_LABEL_STEMS):
            continue
        topic_index = i
        break

    topic = content[topic_index]
    factsheet_parts = content[:topic_index] + content[topic_index + 1 :]

    stripped_parts = []
    for part in factsheet_parts:
        label_match = _LABEL_WORD_RE.match(part)
        if label_match and label_match.group(1).lower().startswith(_LABEL_STEMS):
            part = part[label_match.end() :].strip()
        stripped_parts.append(part)

    return {
        "Runde": round_label,
        "Thema": _strip_quotes(topic),
        "Factsheet": _strip_quotes(
            " ".join(part for part in stripped_parts if part).strip()
        ),
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
    fileName = str(
        ARTICLE_DIR
        / url.removeprefix("https://www.achteminute.de/")
        .replace("/", "_")
        .removesuffix("_")
    )

    if os.path.exists(fileName) and not overwrite:
        with open(fileName, "r", encoding="utf-8") as f:
            html_string = f.read()
            soup = BeautifulSoup(html_string, "html.parser")
        return soup

    try:
        response = _get(url)
    except httpx.HTTPError as e:
        print(f"Error fetching {url}: {e}")
        return []

    soup = _extract_article_body(BeautifulSoup(response.content, "html.parser"))
    ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
    with open(fileName, "w", encoding="utf-8") as f:
        f.write(str(soup))
        f.close()

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
            if label_match and label_match.group(1).lower().startswith(_LABEL_STEMS):
                label_match = None

            if label_match:
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

        entry = _finalize_round(current_round, current_content)
        if entry:
            entries.append(entry)

    tournament_name = _extract_tournament_name(url)

    for entry in entries:
        entry["Link"] = url
        entry["Tournament"] = tournament_name
        entry["Datum"] = date
        if "?" in entry["Thema"]:
            entry["Format"] = "OPD"
        else:
            entry["Format"] = "BP"

    return entries


def _extract_tournament_name(url: str) -> str:
    """
    Gets an URL and extracts the clear name of the tournament. Does not work if the tournament name is not part of the url.
    """
    out = url.removeprefix("https://www.achteminute.de/")
    out = out.split("/")[1]
    pattern_start = re.compile(
        r"(?:gewinnt|gewinnen|siegreich)[- ](?:beim|den|die|das|dem|des|der|einen?|eine[mnrs]?|d[iea]|de[mnrs]?)?\s*(.+)$",
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

    pattern_end = re.compile(
        r"(?:\s+(?:in|bei|am|im|vor|nach|aus|zu|vom|v\.)\s+[\w\s]+$)|(?:\s+\d{4}\s*$)|(?:\s+-\s+[\w\s]+$)",
        re.IGNORECASE,
    )

    out = re.sub(pattern_end, "", out).strip()

    return out


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
        all_topics = []
        for link in tqdm(all_links):
            try:
                all_topics.extend(extract_topics_from_article(link))
            except:
                print(
                    f"WARNING: An exception occured while getting topics from {link}. Skipping article."
                )

        topic_df = pd.DataFrame(all_topics)
        topic_df.to_csv(CACHE_DIR / f"topics_{current_year}.csv")
        current_year += 1


if __name__ == "__main__":
    initial_generation(force_regenerate=True)
