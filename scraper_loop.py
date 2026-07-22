import time
import traceback

from new_topic_checker import check_and_regenerate
from scraping import initial_generation

INTERVAL_SECONDS = 3600

if __name__ == "__main__":
    print("Generating database")
    initial_generation()
    while True:
        try:
            print("Checking current year for new html generation.")
            check_and_regenerate()
        except Exception:
            traceback.print_exc()
        time.sleep(INTERVAL_SECONDS)
