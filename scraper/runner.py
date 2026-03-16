# scraper/runner.py
#
# Orchestrates all site scrapers.
# Run this file directly to scrape all sites and save merged results.
#
# Usage:
#   python -m scraper.runner
#
# What it does:
#   1. Instantiates each scraper.
#   2. Runs them one by one (sequentially — not parallel, to stay polite).
#   3. Merges all results into one list.
#   4. Saves to data/raw_listings.json.

import json
import logging
import sys
from datetime import datetime, UTC
from pathlib import Path

# Add the project root to sys.path so we can import config and scraper modules
# when running this file directly (python -m scraper.runner).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import RAW_DATA_FILE
from scraper.bayut_scraper     import BayutScraper
from scraper.opensooq_scraper  import OpenSooqScraper
from scraper.dubizzle_scraper  import DubizzleScraper
from scraper.savills_scraper   import SavillsScraper
from scraper.tibiaan_scraper   import TibiaanScraper
from scraper.vistaoman_scraper import VistaOmanScraper
from scraper.omanreal_scraper  import OmanrealScraper


# ─── Logging setup ────────────────────────────────────────────────────────────
# Configure once here so all scrapers (which use logging.getLogger) inherit it.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("runner")


# ─── Scraper registry ─────────────────────────────────────────────────────────
# Add new scrapers here. Each entry is a class (not an instance).
# The runner instantiates them at runtime.
SCRAPERS = [
    BayutScraper,
    OpenSooqScraper,
    DubizzleScraper,
    SavillsScraper,
    TibiaanScraper,
    VistaOmanScraper,
    OmanrealScraper,
]


def run_all() -> list[dict]:
    """
    Run every scraper and return a combined list of raw listings.
    Failed scrapers are skipped; their errors are already logged inside run().
    """
    all_listings = []
    total_scrapers = len(SCRAPERS)

    for i, ScraperClass in enumerate(SCRAPERS, start=1):
        scraper = ScraperClass()
        logger.info(f"[{i}/{total_scrapers}] Running {scraper.name} …")

        results = scraper.run()   # run() handles its own exceptions
        all_listings.extend(results)

        logger.info(f"  Subtotal so far: {len(all_listings)} listings")

    return all_listings


def save_results(listings: list[dict]) -> None:
    """
    Write listings to the raw JSON file.
    Creates the data/ directory if it doesn't exist.
    """
    output_path = Path(RAW_DATA_FILE)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Wrap in a metadata envelope so we know when this file was produced.
    output = {
        "scraped_at": datetime.now(UTC).isoformat(),
        "total_listings": len(listings),
        "listings": listings,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved {len(listings)} raw listings → {output_path}")


def main():
    logger.info("═" * 60)
    logger.info("Oman Real Estate Scraper — starting run")
    logger.info("═" * 60)

    listings = run_all()

    logger.info("═" * 60)
    logger.info(f"All scrapers done. Total: {len(listings)} listings")
    logger.info("═" * 60)

    if listings:
        save_results(listings)
    else:
        logger.warning("No listings collected — raw file not written.")


if __name__ == "__main__":
    main()
