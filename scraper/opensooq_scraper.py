# scraper/opensooq_scraper.py
#
# Scrapes property listings from om.opensooq.com.
#
# How OpenSooq works:
#   OpenSooq renders property cards as <a class="postItem"> anchor tags.
#   Each card carries structured data in HTML data-* attributes:
#     data-cat1-code  →  "RealEstateForSale" | "RealEstateForRent"
#     data-city       →  "Muscat"
#     data-nhood      →  neighbourhood name e.g. "Amerat"
#     href            →  full listing URL
#
#   The inner text is formatted like:
#     "24,000 OMR 3 Bedrooms . 3 Bathrooms . 93 m2"
#
#   Pagination uses ?page=N on the /en/real-estate URL.
#   Both sale and rent appear on the same page; we detect type from data-cat1-code.

import re

from bs4 import BeautifulSoup

from config.settings import OPENSOOQ_URL, MAX_PAGES
from scraper.base_scraper import BaseScraper


class OpenSooqScraper(BaseScraper):

    def __init__(self):
        super().__init__(name="opensooq")

    def scrape(self) -> list[dict]:
        all_listings = []
        for page_num in range(1, MAX_PAGES + 1):
            url = OPENSOOQ_URL.format(page=page_num)
            response = self.get(url)
            if response is None:
                self.logger.warning(f"Skipping OpenSooq page {page_num}")
                break
            page_listings = self._parse_page(response.text, url)
            if not page_listings:
                self.logger.info(f"No listings on page {page_num}, stopping")
                break
            all_listings.extend(page_listings)
            self.logger.info(f"  Page {page_num}: {len(page_listings)} listings")
            self.delay()
        return all_listings

    def _parse_page(self, html: str, page_url: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        # Cards are <a class="postItem"> — the anchor IS the card
        cards = soup.find_all("a", class_="postItem")
        return [
            listing
            for card in cards
            if (listing := self._parse_card(card))
        ]

    def _parse_card(self, card) -> dict | None:
        try:
            # ── Listing type from data attribute ───────────────────────────────
            cat_code = card.get("data-cat1-code", "")
            if "ForRent" in cat_code or "ToRent" in cat_code:
                listing_type = "rent"
            elif "ForSale" in cat_code or "Sale" in cat_code:
                listing_type = "sale"
            else:
                listing_type = "unknown"

            # ── Location from data attributes ──────────────────────────────────
            city  = card.get("data-city", "")
            nhood = card.get("data-nhood", "")
            # Prefer neighbourhood; fall back to city
            location = nhood if nhood and nhood.lower() not in ("", "muscat") else city or None

            # ── URL ────────────────────────────────────────────────────────────
            listing_url = card.get("href")

            # ── Inner text: "24,000 OMR 3 Bedrooms . 3 Bathrooms . 93 m2" ─────
            text = card.get_text(" ", strip=True)

            # Price — number followed by OMR
            price = None
            price_match = re.search(r"([\d,]+)\s*OMR", text, re.I)
            if price_match:
                amount = price_match.group(1)
                price = f"OMR {amount}"
                if listing_type == "rent":
                    price += " / month"   # OpenSooq usually shows annual or monthly

            # Beds
            beds = None
            bed_match = re.search(r"(\d+)\s*Bedroom", text, re.I)
            if bed_match:
                beds = int(bed_match.group(1))

            # Baths
            baths = None
            bath_match = re.search(r"(\d+)\s*Bathroom", text, re.I)
            if bath_match:
                baths = int(bath_match.group(1))

            # Size — in m², convert to sqft
            size_sqft = None
            size_match = re.search(r"([\d,]+)\s*m2", text, re.I)
            if size_match:
                sqm = float(size_match.group(1).replace(",", ""))
                size_sqft = int(sqm * 10.764)

            # ── Property type from sub-category ───────────────────────────────
            subcat = card.get("data-sub-category12", "").lower()
            property_type = _subcat_to_type(subcat)

            # Title: OpenSooq cards don't always have a visible title in the card —
            # construct one from the available data as a fallback.
            title_el = card.find(["h2", "h3"])
            if title_el:
                title = title_el.get_text(strip=True)
            else:
                parts = []
                if beds:          parts.append(f"{beds}BR")
                if property_type: parts.append(property_type.title())
                if listing_type != "unknown": parts.append(f"for {listing_type}")
                if location:      parts.append(f"in {location}")
                title = " ".join(parts) or None

            if not price and not title:
                return None

            return self.make_listing(
                title         = title,
                price         = price,
                location      = location,
                bedrooms      = beds,
                bathrooms     = baths,
                size_sqft     = size_sqft,
                property_type = property_type,
                listing_type  = listing_type,
                listing_url   = listing_url,
            )
        except Exception as e:
            self.logger.debug(f"Failed to parse OpenSooq card: {e}")
            return None


def _subcat_to_type(subcat: str) -> str | None:
    """Map OpenSooq sub-category codes to plain English property type."""
    mapping = {
        "apartment": "apartment",
        "villa":     "villa",
        "studio":    "studio",
        "townhouse": "townhouse",
        "shop":      "shop",
        "office":    "office",
        "land":      "land",
        "building":  "building",
    }
    for key, val in mapping.items():
        if key in subcat:
            return val
    return None
