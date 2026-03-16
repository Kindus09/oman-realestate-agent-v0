# tests/test_tools.py
#
# Unit tests for the agent tool functions.
# These tests inject a small set of fake listings so we never touch the real data file.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent.tools as tools_module
from agent.models import Property


# ─── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_LISTINGS = [
    Property(
        title="2BR Apartment in Al Khuwair",
        price_omr=400.0, price_raw="OMR 400 / month", frequency="month",
        location="Al Khuwair", bedrooms=2, bathrooms=2, size_sqft=1100,
        property_type="apartment", listing_type="rent",
        listing_url="https://bayut.com/1", source="bayut",
    ),
    Property(
        title="3BR Villa in Bausher",
        price_omr=650.0, price_raw="OMR 650 / month", frequency="month",
        location="Bausher", bedrooms=3, bathrooms=3, size_sqft=2000,
        property_type="villa", listing_type="rent",
        listing_url="https://dubizzle.com/2", source="dubizzle",
    ),
    Property(
        title="Studio in Al Khuwair",
        price_omr=200.0, price_raw="OMR 200 / month", frequency="month",
        location="Al Khuwair", bedrooms=0, bathrooms=1, size_sqft=450,
        property_type="apartment", listing_type="rent",
        listing_url="https://bayut.com/3", source="bayut",
    ),
    Property(
        title="4BR Villa for Sale in Qurm",
        price_omr=180000.0, price_raw="OMR 180,000", frequency=None,
        location="Qurm", bedrooms=4, bathrooms=4, size_sqft=3500,
        property_type="villa", listing_type="sale",
        listing_url="https://bayut.com/4", source="bayut",
    ),
    Property(
        title="2BR Apartment for Sale in Bausher",
        price_omr=95000.0, price_raw="OMR 95,000", frequency=None,
        location="Bausher", bedrooms=2, bathrooms=2, size_sqft=1200,
        property_type="apartment", listing_type="sale",
        listing_url="https://opensooq.com/5", source="opensooq",
    ),
]


import pytest

@pytest.fixture(autouse=True)
def inject_listings():
    """Inject fake listings before each test and reset the cache after."""
    tools_module._listings_cache = SAMPLE_LISTINGS
    yield
    tools_module._listings_cache = None


# ─── search_listings ──────────────────────────────────────────────────────────

class TestSearchListings:

    def test_no_filters_returns_all(self):
        result = tools_module.search_listings(limit=100)
        assert result["total_found"] == len(SAMPLE_LISTINGS)

    def test_filter_by_listing_type_rent(self):
        result = tools_module.search_listings(listing_type="rent")
        assert result["total_found"] == 3

    def test_filter_by_listing_type_sale(self):
        result = tools_module.search_listings(listing_type="sale")
        assert result["total_found"] == 2

    def test_filter_by_location(self):
        result = tools_module.search_listings(location="Al Khuwair")
        assert result["total_found"] == 2

    def test_filter_by_price_range(self):
        result = tools_module.search_listings(min_price_omr=300.0, max_price_omr=700.0)
        assert result["total_found"] == 2   # 400 and 650

    def test_filter_by_bedrooms(self):
        result = tools_module.search_listings(min_bedrooms=3)
        assert result["total_found"] == 2   # 3BR and 4BR

    def test_filter_by_property_type(self):
        result = tools_module.search_listings(property_type="villa")
        assert result["total_found"] == 2

    def test_filter_by_source(self):
        result = tools_module.search_listings(source="bayut")
        assert result["total_found"] == 3

    def test_limit_respected(self):
        result = tools_module.search_listings(limit=2)
        assert result["returned"] == 2
        assert result["total_found"] == len(SAMPLE_LISTINGS)

    def test_combined_filters(self):
        result = tools_module.search_listings(listing_type="rent", location="Bausher")
        assert result["total_found"] == 1


# ─── get_area_stats ───────────────────────────────────────────────────────────

class TestGetAreaStats:

    def test_known_area(self):
        result = tools_module.get_area_stats("Al Khuwair", "rent")
        assert result["total_listings"] == 2
        assert result["avg_price_omr"] == 300.0   # (400 + 200) / 2
        assert result["min_price_omr"] == 200.0
        assert result["max_price_omr"] == 400.0

    def test_unknown_area_returns_zero(self):
        result = tools_module.get_area_stats("Nowhere")
        assert result["total_listings"] == 0
        assert result["avg_price_omr"] is None

    def test_all_listing_types(self):
        result = tools_module.get_area_stats("Bausher", "all")
        assert result["total_listings"] == 2   # 1 rent + 1 sale

    def test_sources_listed(self):
        result = tools_module.get_area_stats("Al Khuwair", "rent")
        assert "bayut" in result["sources"]


# ─── get_price_range ─────────────────────────────────────────────────────────

class TestGetPriceRange:

    def test_rent_all_bedrooms(self):
        result = tools_module.get_price_range("rent")
        assert result["count"] == 3
        assert result["min_omr"] == 200.0
        assert result["max_omr"] == 650.0

    def test_rent_2_bedrooms(self):
        result = tools_module.get_price_range("rent", bedrooms=2)
        assert result["count"] == 1
        assert result["avg_omr"] == 400.0

    def test_sale(self):
        result = tools_module.get_price_range("sale")
        assert result["count"] == 2
        assert result["min_omr"] == 95000.0

    def test_no_matches_returns_zeros(self):
        result = tools_module.get_price_range("rent", bedrooms=99)
        assert result["count"] == 0
        assert result["avg_omr"] is None


# ─── list_areas ───────────────────────────────────────────────────────────────

class TestListAreas:

    def test_returns_unique_areas(self):
        result = tools_module.list_areas()
        assert "Al Khuwair" in result["areas"]
        assert "Bausher" in result["areas"]
        assert "Qurm" in result["areas"]

    def test_no_duplicates(self):
        result = tools_module.list_areas()
        assert len(result["areas"]) == len(set(result["areas"]))

    def test_sorted(self):
        result = tools_module.list_areas()
        assert result["areas"] == sorted(result["areas"])
