# tests/test_data_cleaner.py
#
# Unit tests for the data cleaning functions.
# Run with:  python -m pytest tests/
#
# These tests don't touch the network or the file system —
# they just verify that the cleaning logic works correctly on sample data.

import sys
from pathlib import Path

# Add project root to path so imports work.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scraper.data_cleaner import parse_price, normalise_location, repair_listing_type, deduplicate, make_fingerprint


# ─── parse_price ──────────────────────────────────────────────────────────────

class TestParsePrice:

    def test_omr_monthly(self):
        result = parse_price("OMR 450 / month")
        assert result["price_omr"] == 450.0
        assert result["frequency"] == "month"

    def test_ro_no_frequency(self):
        result = parse_price("RO 1,200")
        assert result["price_omr"] == 1200.0
        assert result["frequency"] is None

    def test_with_commas(self):
        result = parse_price("OMR 150,000")
        assert result["price_omr"] == 150000.0

    def test_yearly_frequency(self):
        result = parse_price("OMR 5,400 per year")
        assert result["price_omr"] == 5400.0
        assert result["frequency"] == "year"

    def test_non_omr_currency_skipped(self):
        result = parse_price("AED 10,000")
        assert result["price_omr"] is None

    def test_none_input(self):
        result = parse_price(None)
        assert result["price_omr"] is None
        assert result["frequency"] is None

    def test_empty_string(self):
        result = parse_price("")
        assert result["price_omr"] is None

    def test_raw_preserved(self):
        raw = "OMR 800 / month"
        result = parse_price(raw)
        assert result["price_raw"] == raw


# ─── normalise_location ───────────────────────────────────────────────────────

class TestNormaliseLocation:

    def test_exact_alias(self):
        assert normalise_location("al khuwair") == "Al Khuwair"

    def test_case_insensitive(self):
        assert normalise_location("BAUSHER") == "Bausher"

    def test_alias_in_longer_string(self):
        # "khuwair" is a substring alias for "Al Khuwair"
        result = normalise_location("Near Al Khuwair, Muscat")
        assert result == "Al Khuwair"

    def test_bowsher_alias(self):
        assert normalise_location("bowsher") == "Bausher"

    def test_msq_alias(self):
        assert normalise_location("MSQ") == "MQ"

    def test_unknown_location_titlecased(self):
        result = normalise_location("some unknown place")
        assert result == "Some Unknown Place"

    def test_none_returns_none(self):
        assert normalise_location(None) is None


# ─── repair_listing_type ──────────────────────────────────────────────────────

class TestRepairListingType:

    def test_already_rent(self):
        listing = {"listing_type": "rent", "title": "apartment"}
        assert repair_listing_type(listing) == "rent"

    def test_already_sale(self):
        listing = {"listing_type": "sale", "title": "villa"}
        assert repair_listing_type(listing) == "sale"

    def test_infer_rent_from_title(self):
        listing = {"listing_type": "unknown", "title": "3BHK flat for rent in Bausher"}
        assert repair_listing_type(listing) == "rent"

    def test_infer_sale_from_url(self):
        listing = {
            "listing_type": "unknown",
            "title": "",
            "listing_url": "https://example.com/for-sale/villa-muscat"
        }
        assert repair_listing_type(listing) == "sale"

    def test_cannot_infer_stays_unknown(self):
        listing = {"listing_type": "unknown", "title": "Property in Muscat"}
        assert repair_listing_type(listing) == "unknown"


# ─── deduplicate ─────────────────────────────────────────────────────────────

class TestDeduplicate:

    def _listing(self, url=None, title="Test", price_omr=500.0, location="Bausher"):
        return {
            "listing_url": url,
            "title": title,
            "price_omr": price_omr,
            "location": location,
        }

    def test_removes_duplicate_urls(self):
        listings = [
            self._listing(url="https://example.com/1"),
            self._listing(url="https://example.com/1"),  # duplicate
            self._listing(url="https://example.com/2"),
        ]
        result = deduplicate(listings)
        assert len(result) == 2

    def test_removes_duplicate_title_price_location(self):
        listings = [
            self._listing(title="Nice Flat", price_omr=400.0, location="Qurm"),
            self._listing(title="Nice Flat", price_omr=400.0, location="Qurm"),  # duplicate
        ]
        result = deduplicate(listings)
        assert len(result) == 1

    def test_different_prices_kept(self):
        listings = [
            self._listing(title="Nice Flat", price_omr=400.0, location="Qurm"),
            self._listing(title="Nice Flat", price_omr=500.0, location="Qurm"),
        ]
        result = deduplicate(listings)
        assert len(result) == 2

    def test_keeps_first_occurrence(self):
        listings = [
            self._listing(url="https://example.com/1", title="First"),
            self._listing(url="https://example.com/1", title="Second"),
        ]
        result = deduplicate(listings)
        assert result[0]["title"] == "First"

    def test_empty_list(self):
        assert deduplicate([]) == []
