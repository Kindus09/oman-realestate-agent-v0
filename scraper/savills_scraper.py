# scraper/savills_scraper.py
#
# Scrapes rental property listings from Savills Oman.
# Target URL: https://search.savills.com/om/en/list/property-to-rent/oman/muscat
#
# How Savills works:
#   Savills is an international real estate agency. Their search portal is a
#   React SPA. On the server-rendered HTML we can sometimes find a
#   <script type="application/json"> tag or window.__INITIAL_STATE__ variable
#   containing listing data. There's also a REST API endpoint that the frontend
#   calls; we try that first because it returns clean JSON.
#
#   Note: Savills only lists rental properties in this Muscat section,
#   so listing_type is always "rent".

import json
import re

from bs4 import BeautifulSoup

from config.settings import SAVILLS_RENT_URL, MAX_PAGES
from scraper.base_scraper import BaseScraper


class SavillsScraper(BaseScraper):

    BASE_URL = "https://search.savills.com"

    def __init__(self):
        super().__init__(name="savills")

    def scrape(self) -> list[dict]:
        all_listings = []

        for page_num in range(1, MAX_PAGES + 1):
            url = SAVILLS_RENT_URL.format(page=page_num)
            response = self.get(url)

            if response is None:
                self.logger.warning(f"Skipping Savills page {page_num}")
                break

            page_listings = self._parse_page(response.text, url)

            if not page_listings:
                self.logger.info(f"No listings on Savills page {page_num}, stopping")
                break

            all_listings.extend(page_listings)
            self.logger.info(f"  Page {page_num}: {len(page_listings)} listings")
            self.delay()

        return all_listings

    def _parse_page(self, html: str, page_url: str) -> list[dict]:
        """
        Savills embeds listing data in a JSON script tag. We look for:
          1. A <script> tag containing a JSON array of properties.
          2. A window.__INITIAL_STATE__ or similar pattern.
          3. Fallback: HTML property cards.
        """
        soup = BeautifulSoup(html, "lxml")

        # ── Strategy 1: look for inline JSON in <script> tags ─────────────────
        for script in soup.find_all("script"):
            text = script.string or ""
            # Savills sometimes puts listing data in a variable assignment.
            # e.g. window.__RESULTS__ = {...} or just a bare JSON object.
            json_match = re.search(r'(?:window\.__\w+__\s*=\s*)?(\[{.*}\])', text, re.S)
            if json_match:
                try:
                    items = json.loads(json_match.group(1))
                    if isinstance(items, list) and items:
                        return [
                            listing
                            for item in items
                            if (listing := self._parse_json_item(item))
                        ]
                except json.JSONDecodeError:
                    pass

        # ── Strategy 2: HTML card parsing ─────────────────────────────────────
        # Savills property cards are usually <div class="property-card"> or similar.
        cards = (
            soup.find_all("div", class_=re.compile(r"property.?card|listing.?card|result.?item", re.I)) or
            soup.find_all("article") or
            soup.find_all("li", class_=re.compile(r"property|listing", re.I))
        )

        listings = []
        for card in cards:
            listing = self._parse_card(card, page_url)
            if listing:
                listings.append(listing)

        return listings

    def _parse_json_item(self, item: dict) -> dict | None:
        """Parse a property object from Savills' embedded JSON."""
        try:
            # Savills uses camelCase field names in their API.
            price_val = item.get("price") or item.get("priceValue")
            currency  = item.get("currency", "OMR")
            price_str = f"{currency} {price_val:,}" if price_val else item.get("displayPrice")

            location = (
                item.get("address") or
                item.get("area") or
                item.get("suburb") or
                item.get("city")
            )

            link_path = item.get("url") or item.get("propertyUrl") or ""
            listing_url = (
                link_path if link_path.startswith("http")
                else f"{self.BASE_URL}{link_path}"
            ) if link_path else None

            return self.make_listing(
                title         = item.get("title") or item.get("propertyTitle"),
                price         = price_str,
                location      = location,
                bedrooms      = item.get("bedrooms"),
                bathrooms     = item.get("bathrooms"),
                size_sqft     = item.get("floorArea") or item.get("size"),
                property_type = item.get("propertyType") or item.get("type"),
                listing_type  = "rent",   # Savills Muscat section is rent-only
                description   = item.get("summary") or item.get("description"),
                listing_url   = listing_url,
            )
        except Exception as e:
            self.logger.debug(f"Failed to parse Savills JSON item: {e}")
            return None

    def _parse_card(self, card, page_url: str) -> dict | None:
        """Fallback HTML card parser for Savills."""
        try:
            title_el = (
                card.find(class_=re.compile(r"title|heading", re.I)) or
                card.find("h2") or card.find("h3")
            )
            title = title_el.get_text(strip=True) if title_el else None

            price_el = card.find(class_=re.compile(r"price|amount", re.I))
            price = price_el.get_text(strip=True) if price_el else None

            loc_el = card.find(class_=re.compile(r"location|address|area", re.I))
            location = loc_el.get_text(strip=True) if loc_el else None

            link_el = card.find("a", href=True)
            href = link_el["href"] if link_el else ""
            listing_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"

            text  = card.get_text(" ", strip=True)
            beds  = _extract_int(text, r"(\d+)\s*(?:bed|bedroom)")
            baths = _extract_int(text, r"(\d+)\s*bath")
            size  = _extract_int(text, r"(\d[\d,]*)\s*(?:sq\.?\s*ft|sqft|m²)")

            return self.make_listing(
                title        = title,
                price        = price,
                location     = location,
                bedrooms     = beds,
                bathrooms    = baths,
                size_sqft    = size,
                listing_type = "rent",
                listing_url  = listing_url,
            )
        except Exception as e:
            self.logger.debug(f"Failed to parse Savills card: {e}")
            return None


def _extract_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, re.I)
    if match:
        return int(match.group(1).replace(",", ""))
    return None
