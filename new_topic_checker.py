from datetime import datetime, time
from html_generator import generate_html
from scraping import extract_topics_from_article, get_all_article_links
import os
import json
import pandas as pd

from paths import CACHE_DIR, OUTPUT_DIR
from topic_merger import clean_df, merge_csv_files_with_dedup


def check_new_articles():
    current_year = datetime.now().year
    link_file = CACHE_DIR / f"{current_year}_links.json"
    if os.path.exists(link_file):
        with open(link_file, "r") as f:
            links = json.load(f)
    else:
        print("Link file does not exist")
        links = []

    all_links = get_all_article_links(
        start_year=current_year, start_month=1, end_year=current_year, end_month=12
    )

    new_links = [x for x in all_links if x not in links]

    if len(new_links) > 0:
        print(f"Found {len(new_links)} new Articles!")
        return all_links

    return []


def regenerate_topics_from_cache():
    """
    Re-extracts topics for every previously-seen article link, using only
    the cached HTML in ARTICLE_DIR (no network fetches for articles already
    downloaded), then rebuilds topics.csv and index.html.

    Link lists come from CACHE_DIR/{year}_links.json when available; years
    without one (i.e. every year except the current one, which is the only
    one check_new_articles maintains a link file for) fall back to the
    "Link" column of that year's existing topics_{year}.csv, so historical
    years get re-extracted too instead of only ever getting the version
    produced by whichever extraction logic was current when they were
    first scraped.
    """
    years_with_link_file = set()
    for link_file in sorted(CACHE_DIR.glob("*_links.json")):
        year = link_file.stem.removesuffix("_links")
        years_with_link_file.add(year)
        with open(link_file, "r") as f:
            links = json.load(f)
        _reextract_year(year, links)

    for topics_file in sorted(CACHE_DIR.glob("topics_[0-9][0-9][0-9][0-9].csv")):
        year = topics_file.stem.removeprefix("topics_")
        if year in years_with_link_file:
            continue
        df = pd.read_csv(topics_file)
        if "Link" not in df.columns:
            continue
        links = df["Link"].dropna().unique().tolist()
        _reextract_year(year, links)

    regenerate_site()


def _reextract_year(year: str, links: list) -> None:
    print(f"Re-extracting topics for {len(links)} articles from {year}...")
    all_topics = []
    for link in links:
        all_topics.extend(extract_topics_from_article(link))

    topic_df = pd.DataFrame(all_topics)
    topic_df.to_csv(CACHE_DIR / f"topics_{year}.csv", index=False)


def regenerate_site():
    """Rebuilds topics.csv and index.html from the cached per-year csvs."""
    merged_df = merge_csv_files_with_dedup(dedup_column="Thema", verify_column="Link")
    cleaned_df = clean_df(merged_df)
    print(f"Writing {len(cleaned_df)} topics to csv.")
    cleaned_df.to_csv(OUTPUT_DIR / "topics.csv", index=False)
    merged_df.to_csv(CACHE_DIR / "topics_full.csv", index=False)

    print("Generating new html")
    generate_html(OUTPUT_DIR / "topics.csv", OUTPUT_DIR / "index.html")
    print("Successfully generated new html")


def check_and_regenerate():
    all_links = check_new_articles()

    ## If there are new links, regenerate the DataFrame for the current year
    if len(all_links) > 0:
        all_topics = []
        print("Extracting topics from articles...")
        for link in all_links:
            all_topics.extend(extract_topics_from_article(link))

        current_year = datetime.now().year
        topic_df = pd.DataFrame(all_topics)
        topic_df.to_csv(CACHE_DIR / f"topics_{current_year}.csv", index=False)

        ## Write the current state of links to the json
        link_file = CACHE_DIR / f"{current_year}_links.json"
        with open(link_file, "w") as f:
            json.dump(all_links, f)

        regenerate_site()

    else:
        print("No new topics found.")


if __name__ == "__main__":
    check_and_regenerate()
