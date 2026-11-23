"""Filesystem locations, configurable via environment variables."""

import os
from pathlib import Path

# Scraper state that is expensive to rebuild, persisted via a docker volume
CACHE_DIR = Path(os.environ.get("CACHE_DIR", "cache/"))

# Generated site served by the web container
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "."))

ARTICLE_DIR = CACHE_DIR / "articles"


def ensure_dirs() -> None:
    """Creates the article cache and output directories if they are missing."""
    ARTICLE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
