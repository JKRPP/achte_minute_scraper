"""Detects newly published articles and regenerates the topic data and site."""

import json
import os
from datetime import datetime

import pandas as pd

from html_generator import generate_html
from paths import CACHE_DIR, OUTPUT_DIR
from scraping import extract_topics_for_links, get_all_article_links
from topic_merger import build_topics_csv


def check_new_articles():
    """Returns all of this year's article links if any are new, otherwise an empty list."""
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
    """Re-extracts topics for every known article from the article cache, then rebuilds the site."""
    years_with_link_file = set()
    for link_file in sorted(CACHE_DIR.glob("*_links.json")):
        year = link_file.stem.removesuffix("_links")
        years_with_link_file.add(year)
        with open(link_file, "r") as f:
            links = json.load(f)
        _reextract_year(year, links)

    # Years without a link file can only recover their links from the topics csv
    for topics_file in sorted(CACHE_DIR.glob("topics_[0-9][0-9][0-9][0-9].csv")):
        year = topics_file.stem.removeprefix("topics_")
        if year in years_with_link_file:
            continue
        try:
            df = pd.read_csv(topics_file)
        except pd.errors.EmptyDataError:
            continue
        if "Link" not in df.columns:
            continue
        links = df["Link"].dropna().unique().tolist()
        _reextract_year(year, links)

    regenerate_site()


def _reextract_year(year: str, links: list) -> None:
    """Re-extracts one year's articles and overwrites its topics csv."""
    print(f"Re-extracting topics for {len(links)} articles from {year}...")
    topic_df = extract_topics_for_links(links)
    topic_df.to_csv(CACHE_DIR / f"topics_{year}.csv", index=False)


def regenerate_site():
    """Rebuilds topics.csv and index.html from the cached per-year csvs."""
    build_topics_csv()

    print("Generating new html")
    generate_html(OUTPUT_DIR / "topics.csv", OUTPUT_DIR / "index.html")
    print("Successfully generated new html")


def check_and_regenerate():
    """Re-extracts the current year and rebuilds the site if new articles were published."""
    all_links = check_new_articles()

    if len(all_links) > 0:
        print("Extracting topics from articles...")
        current_year = datetime.now().year
        topic_df = extract_topics_for_links(all_links)
        topic_df.to_csv(CACHE_DIR / f"topics_{current_year}.csv", index=False)

        # Written last, so a failed extraction is retried on the next run
        link_file = CACHE_DIR / f"{current_year}_links.json"
        with open(link_file, "w") as f:
            json.dump(all_links, f)

        regenerate_site()

    else:
        print("No new topics found.")


if __name__ == "__main__":
    check_and_regenerate()
