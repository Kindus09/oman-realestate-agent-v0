# scraper/bayut_scraper.py
#
# Scrapes property listings from Bayut.com/oman for Muscat.
# Targets both for-sale and for-rent listings.
#
# ⚠️  Anti-bot protection note:
#   Bayut currently deploys a JavaScript-based bot challenge (similar to
#   Cloudflare's "I'm not a robot" check). Plain HTTP requests receive an
#   obfuscated JS page instead of the real HTML, so BeautifulSoup finds
#   no listings.
#
#   This scraper is structured and ready for when the protection is bypassed,
#   for example by:
#     - Using a headless browser (Playwright/Selenium) — swap out self.get()
#       for a Playwright page.goto() call.
#     - Using a proxy service that handles JS challenges (e.g. ScraperAPI,
#       Zyte, Oxylabs).
#     - Waiting for Bayut to serve HTML to regular requests for Oman pages.
#
#   When the protection is active, this scraper logs a warning and returns [].
#   The rest of the pipeline continues unaffected.
#
# How Bayut works (when accessible):
#   Bayut is a Next.js app and embeds listing data in a
#   <script id="__NEXT_DATA__" type="application/json"> tag.
#   We parse that JSON instead of fragile CSS selectors.
#   Fallback: HTML card parsing using <article data-testid="property-card">.

import json
import logging
import re

from bs4 import BeautifulSoup

from config.settings import BAYUT_SALE_URL, BAYUT_RENT_URL, MAX_PAGES
from scraper.base_scraper import BaseScraper

logger = logging.getLogger(__name__)

# Text that appears in Bayut's bot-challenge page (not in a real listing page)
_BOT_CHALLENGE_MARKERS = ["WPHvAZCK", "function m(){var qmQ=", "WQSKhYO"]


class BayutScraper(BaseScraper):

    def __init__(self):
        super().__init__(name="bayut")

    def scrape(self) -> list[dict]:
        listings = []
        for listing_type, url_template in [
            ("sale", BAYUT_SALE_URL),
            ("rent", BAYUT_RENT_URL),
        ]:
            self.logger.info(f"Scraping Bayut — {listing_type} listings")
            page_results = self._scrape_listing_type(listing_type, url_template)
            listings.extend(page_results)
            self.logger.info(f"  → {len(page_results)} {listing_type} listings from Bayut")
        return listings

    def _scrape_listing_type(self, listing_type: str, url_template: str) -> list[dict]:
        all_listings = []
        for page_num in range(1, MAX_PAGES + 1):
            url = url_template.format(page=page_num)
            response = self.get(url)
            if response is None:
                self.logger.warning(f"Skipping Bayut page {page_num} ({listing_type}) — request failed")
                break

            # Detect bot challenge page
            if any(marker in response.text for marker in _BOT_CHALLENGE_MARKERS):
                self.logger.warning(
                    "Bayut is serving a bot-challenge page — cannot scrape without a headless browser. "
                    "See bayut_scraper.py comments for how to work around this."
                )
                break

            page_listings = self._parse_page(response.text, listing_type, url)
            if not page_listings:
                self.logger.info(f"No listings on page {page_num}, stopping early")
                break

            all_listings.extend(page_listings)
            self.logger.info(f"  Page {page_num}: {len(page_listings)} listings")
            self.delay()

        return all_listings

    def _parse_page(self, html: str, listing_type: str, page_url: str) -> list[dict]:
        listings = []
        soup = BeautifulSoup(html, "lxml")

        # ── Strategy 1: __NEXT_DATA__ embedded JSON ───────────────────────────
        try:
            next_data_tag = soup.find("script", {"id": "__NEXT_DATA__"})
            if next_data_tag and next_data_tag.string:
                data = json.loads(next_data_tag.string)
                hits = (
                    data.get("props", {})
                        .get("pageProps", {})
                        .get("searchResult", {})
                        .get("hits", [])
                )
                if hits:
                    for hit in hits:
                        listing = self._parse_hit(hit, listing_type)
                        if listing:
                            listings.append(listing)
                    return listings
        except (json.JSONDecodeError, AttributeError, KeyError) as e:
            self.logger.debug(f"__NEXT_DATA__ parse failed: {e}")

        # ── Strategy 2: HTML card parsing (fallback) ──────────────────────────
        cards = (
            soup.find_all("article", attrs={"data-testid": "property-card"}) or
            soup.find_all("article")
        )
        for card in cards:
            listing = self._parse_card(card, listing_type, page_url)
            if listing:
                listings.append(listing)

        return listings

    def _parse_hit(self, hit: dict, listing_type: str) -> dict | None:
        try:
            price_val = hit.get("price")
            currency  = hit.get("currency", "OMR")
            if price_val:
                price_str = f"{currency} {price_val:,}"
                if listing_type == "rent":
                    freq = hit.get("rentFrequency", "")
                    price_str += f" / {freq}" if freq else ""
            else:
                price_str = None

            location_parts = hit.get("location", [])
            if isinstance(location_parts, list) and location_parts:
                location = location_parts[-1].get("name")
            elif isinstance(location_parts, dict):
                location = location_parts.get("name")
            else:
                location = None

            slug = hit.get("slug") or hit.get("externalID", "")
            listing_url = f"https://www.bayut.com/property/details-{slug}.html" if slug else None

            return self.make_listing(
                title         = hit.get("title"),
                price         = price_str,
                location      = location,
                bedrooms      = hit.get("rooms"),
                bathrooms     = hit.get("baths"),
                size_sqft     = hit.get("area"),
                property_type = hit.get("type", {}).get("name") if isinstance(hit.get("type"), dict) else hit.get("type"),
                listing_type  = listing_type,
                description   = hit.get("description"),
                listing_url   = listing_url,
            )
        except Exception as e:
            self.logger.debug(f"Failed to parse hit: {e}")
            return None

    def _parse_card(self, card, listing_type: str, page_url: str) -> dict | None:
        try:
            title_el = (
                card.find("h2") or
                card.find(attrs={"data-testid": "listing-name"}) or
                card.find(class_=re.compile(r"title", re.I))
            )
            title = title_el.get_text(strip=True) if title_el else None

            price_el = card.find(attrs={"data-testid": "property-price"}) or \
                       card.find(class_=re.compile(r"price", re.I))
            price = price_el.get_text(strip=True) if price_el else None

            loc_el = card.find(attrs={"data-testid": "property-location"}) or \
                     card.find(class_=re.compile(r"location|address", re.I))
            location = loc_el.get_text(strip=True) if loc_el else None

            beds = baths = size = None
            for item in card.find_all(attrs={"aria-label": True}):
                label = item["aria-label"].lower()
                text  = item.get_text(strip=True)
                if "bed" in label:
                    beds = _parse_int(text)
                elif "bath" in label:
                    baths = _parse_int(text)
                elif "area" in label or "sqft" in label:
                    size = _parse_int(text.replace(",", ""))

            link_el = card.find("a", href=True)
            if link_el:
                href = link_el["href"]
                listing_url = href if href.startswith("http") else f"https://www.bayut.com{href}"
            else:
                listing_url = page_url

            return self.make_listing(
                title        = title,
                price        = price,
                location     = location,
                bedrooms     = beds,
                bathrooms    = baths,
                size_sqft    = size,
                listing_type = listing_type,
                listing_url  = listing_url,
            )
        except Exception as e:
            self.logger.debug(f"Failed to parse card: {e}")
            return None


def _parse_int(text: str) -> int | None:
    if not text:
        return None
    match = re.search(r"\d[\d,]*", text)
    if match:
        return int(match.group().replace(",", ""))
    return None
