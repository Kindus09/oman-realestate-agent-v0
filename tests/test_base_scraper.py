# tests/test_base_scraper.py
#
# Tests for BaseScraper utility methods.
# We use a concrete subclass (MinimalScraper) to test the base class
# since BaseScraper itself is abstract.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.base_scraper import BaseScraper, PROPERTY_SCHEMA


class MinimalScraper(BaseScraper):
    """Minimal concrete subclass for testing BaseScraper."""
    def __init__(self):
        super().__init__(name="test")

    def scrape(self):
        return []


class TestMakeListing:

    def setup_method(self):
        self.scraper = MinimalScraper()

    def test_all_schema_keys_present(self):
        listing = self.scraper.make_listing()
        for key in PROPERTY_SCHEMA:
            assert key in listing

    def test_source_auto_filled(self):
        listing = self.scraper.make_listing()
        assert listing["source"] == "test"

    def test_date_scraped_auto_filled(self):
        listing = self.scraper.make_listing()
        assert listing["date_scraped"] is not None
        # Should be an ISO date string like "2026-03-16"
        assert len(listing["date_scraped"]) == 10

    def test_kwargs_override_defaults(self):
        listing = self.scraper.make_listing(title="Test Property", bedrooms=3)
        assert listing["title"] == "Test Property"
        assert listing["bedrooms"] == 3

    def test_unset_fields_are_none(self):
        listing = self.scraper.make_listing(title="Only Title")
        assert listing["price"] is None
        assert listing["location"] is None
        assert listing["bathrooms"] is None


class TestRunMethod:

    def test_run_returns_list(self):
        scraper = MinimalScraper()
        result = scraper.run()
        assert isinstance(result, list)

    def test_run_handles_exception_gracefully(self):
        """If scrape() raises, run() should catch it and return an empty list."""
        class BrokenScraper(BaseScraper):
            def __init__(self):
                super().__init__(name="broken")
            def scrape(self):
                raise RuntimeError("Simulated failure")

        scraper = BrokenScraper()
        result = scraper.run()
        assert result == []
