# scraper/base_scraper.py
#
# BaseScraper is the parent class that every site-specific scraper inherits from.
# It handles the plumbing that every scraper needs:
#   - a shared requests.Session with realistic headers
#   - polite random delays between requests
#   - structured logging
#   - saving results to a JSON file
#
# Each child class only needs to implement `scrape()`, which returns a list of
# property dicts in the shared schema defined below.

import json
import logging
import random
import time
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

import requests

from config.settings import DEFAULT_HEADERS, REQUEST_DELAY_MIN, REQUEST_DELAY_MAX, REQUEST_TIMEOUT


# ─── Shared property schema ───────────────────────────────────────────────────
# Every scraper must return a list of dicts with these keys.
# Use None for any field that the site doesn't provide.
PROPERTY_SCHEMA = {
    "title":         None,
    "price":         None,   # raw string from the site, e.g. "OMR 450 / month"
    "location":      None,   # area / neighbourhood name
    "bedrooms":      None,   # int or None
    "bathrooms":     None,   # int or None
    "size_sqft":     None,   # int or None
    "property_type": None,   # "apartment", "villa", "townhouse", etc.
    "listing_type":  None,   # "sale" or "rent"
    "description":   None,
    "listing_url":   None,
    "source":        None,   # scraper name, e.g. "bayut"
    "date_scraped":  None,   # ISO date string, filled in by BaseScraper
}


class BaseScraper(ABC):
    """
    Abstract base class for all site scrapers.

    Usage
    -----
    Subclass this, implement `scrape()`, and call `run()` to execute.

        class MyScraper(BaseScraper):
            def scrape(self):
                listings = []
                ...
                return listings

        scraper = MyScraper(name="mysite")
        results = scraper.run()
    """

    def __init__(self, name: str):
        self.name = name
        self.today = date.today().isoformat()

        # One shared requests.Session per scraper instance.
        # Sessions reuse TCP connections, which is faster and friendlier.
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

        # Each scraper gets its own logger named after the site.
        self.logger = logging.getLogger(f"scraper.{name}")

    # ── Helpers available to all child classes ────────────────────────────────

    def get(self, url: str) -> requests.Response | None:
        """
        Fetch a URL with error handling.
        Returns the Response object, or None if the request failed.
        Always call `self.delay()` before the next request.
        """
        try:
            self.logger.info(f"GET {url}")
            response = self.session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()   # raises an exception for 4xx / 5xx
            return response
        except requests.exceptions.HTTPError as e:
            self.logger.warning(f"HTTP error fetching {url}: {e}")
        except requests.exceptions.ConnectionError as e:
            self.logger.warning(f"Connection error fetching {url}: {e}")
        except requests.exceptions.Timeout:
            self.logger.warning(f"Timeout fetching {url}")
        except requests.exceptions.RequestException as e:
            self.logger.warning(f"Request failed for {url}: {e}")
        return None

    def delay(self):
        """Sleep for a random amount of time to be polite to the server."""
        seconds = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
        self.logger.debug(f"Sleeping {seconds:.1f}s …")
        time.sleep(seconds)

    def make_listing(self, **kwargs) -> dict:
        """
        Build a listing dict from keyword arguments, filling in defaults
        from PROPERTY_SCHEMA for any missing keys.
        Always stamps `source` and `date_scraped`.
        """
        listing = dict(PROPERTY_SCHEMA)   # start with all-None defaults
        listing.update(kwargs)
        listing["source"]       = self.name
        listing["date_scraped"] = self.today
        return listing

    # ── Core interface ────────────────────────────────────────────────────────

    @abstractmethod
    def scrape(self) -> list[dict]:
        """
        Fetch and parse listings from the target site.
        Must return a list of dicts that match PROPERTY_SCHEMA.
        Implement this in every subclass.
        """
        ...

    def run(self) -> list[dict]:
        """
        Entry point. Calls `scrape()`, logs a summary, and returns results.
        Call this from runner.py.
        """
        self.logger.info(f"Starting scrape: {self.name}")
        try:
            results = self.scrape()
        except Exception as e:
            # Catch-all so one broken scraper doesn't kill the whole run.
            self.logger.error(f"Scraper '{self.name}' failed with an unexpected error: {e}", exc_info=True)
            results = []
        self.logger.info(f"Finished {self.name}: {len(results)} listings collected")
        return results
