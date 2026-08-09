import os
from pathlib import Path

## Scraper state that is expensive to rebuild (downloaded articles, per-year
## topic csvs, link lists). Persisted across rebuilds via a docker volume.
CACHE_DIR = Path(os.environ.get("CACHE_DIR", "."))

## Generated site the web container serves.
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "."))

ARTICLE_DIR = CACHE_DIR / "articles"


def ensure_dirs() -> None:
    ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
