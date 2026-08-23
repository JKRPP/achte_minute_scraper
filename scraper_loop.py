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

    ## Always re-extract topics from cached articles and rebuild the site on
    ## startup, so a redeploy with updated scraping/extraction logic is
    ## reflected immediately without a manual "site_rebuilder.py --from-cache".
    print("Re-extracting topics from cache and regenerating site.")
    regenerate_topics_from_cache()
    while True:
        ## Check for new topics every hour
        try:
            print("Checking current year for new html generation.")
            check_and_regenerate()
        except Exception:
            traceback.print_exc()
        time.sleep(INTERVAL_SECONDS)
