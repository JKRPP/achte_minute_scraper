from pathlib import Path
import re
import requests
from bs4 import BeautifulSoup, NavigableString
from datetime import datetime
from typing import List, Optional, Dict
import pandas as pd

_QUOTE_CHARS = "\"'„“”‚‘’«»"

_LABEL_WORD_RE = re.compile(r"^([A-Za-zÀ-ÿ]+)\s*:?\s*")
_LABEL_STEMS = ("info", "fact", "definition")
_DATE_IN_URL_RE = re.compile(r"/(\d{8})/")
_ROUND_LABEL_LINE_RE = re.compile(
    r"^\(?([A-Za-zÄÖÜäöüß\-]{1,25}\s?[0-9]{0,3}):\s*(.*)$", re.DOTALL
)


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
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return []

    soup = BeautifulSoup(response.content, "html.parser")
    article_pattern = re.compile(
        rf"^https://www\.achteminute\.de/{year}{month:02d}\d{{2}}/.+/$"
    )

    article_links = []
    for a_tag in soup.find_all("a", href=True, rel="bookmark"):
        href = a_tag["href"]
        if article_pattern.match(href) and href not in article_links:
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
    entry. The topic is always the *last* segment of the round (whatever
    precedes it — factsheet, infoslide, bonus links, dialogue snippets — is
    joined together as the factsheet), since that's the only positional rule
    that holds across articles: some factsheets are explicitly labelled
    ("Factsheet: ..."), some aren't, and some rounds have extra segments
    (e.g. "+ ein Video: ...") wedged between the factsheet and the topic.
    """
    if round_label is None or not content:
        return None

    topic = content[-1]
    factsheet_parts = content[:-1]

    if factsheet_parts:
        info_match = _LABEL_WORD_RE.match(factsheet_parts[0])
        if info_match and info_match.group(1).lower().startswith(_LABEL_STEMS):
            factsheet_parts[0] = factsheet_parts[0][info_match.end() :].strip()

    return {
        "Runde": round_label,
        "Thema": _strip_quotes(topic),
        "Factsheet": _strip_quotes(
            " ".join(part for part in factsheet_parts if part).strip()
        ),
    }


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
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return []

    soup = BeautifulSoup(response.content, "html.parser")
    date = extract_date_from_url(url)

    entries = []
    for blockquote in soup.find_all("blockquote"):
        current_round = None
        current_content: List[str] = []

        for segment in _blockquote_segments(blockquote):
            label_match = _ROUND_LABEL_LINE_RE.match(segment)

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

    for entry in entries:
        entry["Link"] = url
        entry["Datum"] = date
        if "?" in entry["Thema"]:
            entry["Format"] = "OPD"
        else:
            entry["Format"] = "BP"

    return entries


def initial_generation():
    first_year = 2013
    last_year = datetime.now().year

    current_year = first_year

    while current_year <= last_year:
        print(f"Getting topics from {current_year}")
        if Path(f"topics_{current_year}.csv").exists():
            print(
                f"File topics_{current_year}.csv already exists. Skipping file in initial generation."
            )
            current_year += 1
            continue
        all_links = get_all_article_links(
            start_year=current_year, start_month=1, end_year=current_year, end_month=12
        )
        all_topics = []
        for link in all_links:
            all_topics.extend(extract_topics_from_article(link))

        topic_df = pd.DataFrame(all_topics)
        topic_df.to_csv(f"topics_{current_year}.csv")
        current_year += 1


if __name__ == "__main__":
    initial_generation()
