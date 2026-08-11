import argparse

from new_topic_checker import regenerate_site, regenerate_topics_from_cache
from scraping import initial_generation

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manual regeneration of the site.")
    parser.add_argument(
        "--from-cache",
        action="store_true",
        help=(
            "Re-extract topics from already-cached articles/link lists only, "
            "without fetching article/link lists over the network."
        ),
    )
    args = parser.parse_args()

    print("Manual regeneration of site triggered.")
    if args.from_cache:
        regenerate_topics_from_cache()
    else:
        initial_generation(force_regenerate=True)
        regenerate_site()
