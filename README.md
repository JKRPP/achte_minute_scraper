# Achte Minute Scraper

Scrapes debate motions from tournament reports on [achteminute.de](https://www.achteminute.de/) and publishes them as a searchable, filterable static web page.

## How it works

1. **Discovery** (`scraping.get_article_links_from_month`) walks achteminute.de's monthly archive pages and collects links to articles tagged "Turniere". (Important: If articles are not tagged correctly, they won't be discovered. Motions from Discussion articles will not be included.)
2. **Extraction** (`scraping.extract_topics_from_article`) downloads the discovered articles into the `articles/` folder and parses the `<blockquote>` block containing the round-by-round motions, and pulls out round label, topic, factsheet/infoslide, format (BP/OPD) and detected language for every round.
3. **Merging and cleanup** (`topic_merger.py`) combines the per-year CSVs, deduplicates, drops known-bad rows and normalizes round labels (e.g. `R1` → `VR1`) via `data/round_translations.json`.
4. **Site generation** (`html_generator.py`) renders the merged CSV into a single self-contained `index.html` (search, year-range/format/language/infoslide/outround filters, sortable table).

## Running it

### Installation

Requires Python 3.12. To install the dependencies via pip:

```bash
pip install -r requirements.txt
```

### Running the code

- `scraper_loop.py` long-running process: does an initial full scrape, regenerates the site, then polls for new articles every hour. This is what runs in the `scraper` container (see `Dockerfile.scraper` / `docker-compose.yml`).
- `site_rebuilder.py`: one-off manual regeneration:
  - `python site_rebuilder.py`: full re-scrape (fetches link lists and articles over the network) and rebuild.
  - `python site_rebuilder.py --from-cache`: re-run extraction against already-downloaded articles only (no network calls), then rebuild. Useful after changing extraction logic in `scraping.py`.
- `python html_generator.py [path/to/topics.csv]`: regenerate just `index.html` from an existing CSV (defaults to `topics.csv`).

## Data files

- `topics.csv`: the merged, cleaned dataset that feeds the website.
- `data/round_translations.json`: maps raw round-label variants (e.g. `"HF 1"`, `"Runde 2"`) to canonical names.
- `data/tournament_title_replacements.json`: cleans up tournament names extracted from URLs.
- `data/drop_round_values.json`: round labels to exclude entirely (known-bad data).

## Deployment

`docker-compose.yml` runs two containers: `scraper` (this codebase, writing to a shared `cache`/`site` volume) and `web` (nginx serving the generated `site` volume as static files). Requires the `${PROXY_NETWORK}` environment variable to be set for easy integration into reverse-proxy setups.

## Live version

A running live version of the resulting site can be found at [themen.krapp.io](https://themen.krapp.io/)