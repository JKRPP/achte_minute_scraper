"""Long-running scraper: builds the database once, then checks for new articles hourly."""

import time
import traceback

from new_topic_checker import check_and_regenerate, regenerate_topics_from_cache
from paths import ensure_dirs
from scraping import initial_generation

INTERVAL_SECONDS = 3600

if __name__ == "__main__":
    ensure_dirs()
    print("Generating database")
    initial_generation()

    # Re-extract on every startup so extraction changes take effect on redeploy
    print("Re-extracting topics from cache and regenerating site.")
    regenerate_topics_from_cache()
    while True:
        try:
            print("Checking current year for new html generation.")
            check_and_regenerate()
        except Exception:
            traceback.print_exc()
        time.sleep(INTERVAL_SECONDS)
