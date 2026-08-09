import time
import traceback

from new_topic_checker import check_and_regenerate, regenerate_site
from paths import ensure_dirs
from scraping import initial_generation

INTERVAL_SECONDS = 3600

if __name__ == "__main__":
    ensure_dirs()
    print("Generating database")
    initial_generation()

    ## Always rebuild the site on startup
    print("Regenerating site from cache.")
    regenerate_site()
    while True:
        ## Check for new topics every hour
        try:
            print("Checking current year for new html generation.")
            check_and_regenerate()
        except Exception:
            traceback.print_exc()
        time.sleep(INTERVAL_SECONDS)
