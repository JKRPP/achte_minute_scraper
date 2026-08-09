import time
import traceback

from new_topic_checker import check_and_regenerate, regenerate_site
from paths import OUTPUT_DIR, ensure_dirs
from scraping import initial_generation

INTERVAL_SECONDS = 3600

if __name__ == "__main__":
    ensure_dirs()
    print("Generating database")
    initial_generation()

    ## On a fresh output volume there is no site yet, and check_and_regenerate
    ## only writes one when it finds new articles.
    if not (OUTPUT_DIR / "index.html").exists():
        print("No site found, generating from cache.")
        regenerate_site()
    while True:
        try:
            print("Checking current year for new html generation.")
            check_and_regenerate()
        except Exception:
            traceback.print_exc()
        time.sleep(INTERVAL_SECONDS)
