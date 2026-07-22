from datetime import datetime, time
from pathlib import Path
from html_generator import generate_html
from scraping import extract_topics_from_article, get_all_article_links
import os
import json
import pandas as pd

from topic_merger import clean_df, merge_csv_files_with_dedup


def check_new_articles():
    current_year = datetime.now().year
    link_file = f"{current_year}_links.json"
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
        topic_df.to_csv(f"topics_{current_year}.csv")

        ## Write the current state of links to the json
        link_file = f"{current_year}_links.json"
        with open(link_file, "w") as f:
            json.dump(all_links, f)

        ## Regenerate the csv
        merged_df = merge_csv_files_with_dedup(
            dedup_column="Thema", verify_column="Link"
        )
        cleaned_df = clean_df(merged_df)
        print(f"Writing {len(cleaned_df)} topics to csv.")
        cleaned_df.to_csv("topics.csv")
        merged_df.to_csv("topics_full.csv")

        ## Regenerate the html
        print("Generating new html")
        csv_path = Path("topics.csv")
        html_path = Path("index.html")
        generate_html(csv_path, html_path)

        print("Successfully generated new html")

    else:
        print("No new topics found.")


if __name__ == "__main__":
    check_and_regenerate()
