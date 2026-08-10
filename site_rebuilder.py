from new_topic_checker import regenerate_site
from scraping import initial_generation

if __name__ == "__main__":
    print("Manual regeneration of site triggered.")
    initial_generation(force_regenerate=True)
    regenerate_site()
