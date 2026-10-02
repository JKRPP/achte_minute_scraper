import re
import time
from datetime import datetime, timedelta

import httpx
import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm

from paths import ARTICLE_DIR, CACHE_DIR
from topic_extraction import extract_topics_from_article

_http_client = httpx.Client(http2=True, headers={"User-Agent": "Mozilla/5.0"})

_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2


_DATE_IN_URL_RE = re.compile(r"/(\d{8})/")

# WordPress category ID for "Turniere"
_TURNIERE_CATEGORY_ID = 46


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
    end_year: int | None = None,
    end_month: int | None = None,
) -> list[str]:
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


def extract_date_from_url(url: str) -> str | None:
    """Article URLs encode their publish date as /YYYYMMDD/ (e.g. /20260521/...)."""
    match = _DATE_IN_URL_RE.search(url)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date().isoformat()
    except ValueError:
        return None


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


def extract_topics_for_links(
    links: list[str], show_progress: bool = False
) -> pd.DataFrame:
    """
    Extracts topics for a list of article links into a single DataFrame,
    skipping (and logging) any article that fails to extract instead of
    aborting the whole batch.
    """
    all_topics = []
    for link in tqdm(links) if show_progress else links:
        try:
            article = download_article(link)
            date = extract_date_from_url(link)
            all_topics.extend(extract_topics_from_article(article, date, link))
        except Exception as e:
            print(
                f"WARNING: Failed to get topics from {link}: {e!r}. Skipping article."
            )

    return pd.DataFrame(all_topics)


def initial_generation(starting_year=2008, force_regenerate=False, verbose=False):
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
