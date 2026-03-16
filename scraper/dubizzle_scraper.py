# scraper/dubizzle_scraper.py
#
# Scrapes property listings from dubizzle.com.om (Oman edition of Dubizzle).
#
# How Dubizzle Oman works:
#   Dubizzle uses hashed CSS class names (they change on every deploy) and
#   serves Arabic content. We cannot rely on class names for parsing.
#   Instead we:
#     1. Find all <article> tags (the card wrapper — this is stable).
#     2. Within each article, use tag-type selectors (h2 for title,
#        <a href> for URL) and regex on the full text for price/size/location.
#
#   Price format: "435 ر. ع شهرياً"  →  435 OMR / month
#     ر. ع = Rial Omani (Arabic abbreviation)
#     شهرياً = monthly | سنوياً = yearly
#
#   Location format: "الخوير، مسقط" (Arabic: Al Khuwair, Muscat)
#     We extract the English part from the title when Arabic location isn't parseable.
#
#   Pagination: ?page=N appended to the listing URL.

import re

from bs4 import BeautifulSoup

from config.settings import DUBIZZLE_SALE_URL, DUBIZZLE_RENT_URL, MAX_PAGES
from scraper.base_scraper import BaseScraper


class DubizzleScraper(BaseScraper):

    BASE_URL = "https://www.dubizzle.com.om"

    def __init__(self):
        super().__init__(name="dubizzle")

    def scrape(self) -> list[dict]:
        listings = []
        for listing_type, url_template in [
            ("sale", DUBIZZLE_SALE_URL),
            ("rent", DUBIZZLE_RENT_URL),
        ]:
            self.logger.info(f"Scraping Dubizzle — {listing_type} listings")
            results = self._scrape_type(listing_type, url_template)
            listings.extend(results)
            self.logger.info(f"  → {len(results)} {listing_type} listings from Dubizzle")
        return listings

    def _scrape_type(self, listing_type: str, url_template: str) -> list[dict]:
        all_listings = []
        for page_num in range(1, MAX_PAGES + 1):
            url = url_template.format(page=page_num)
            response = self.get(url)
            if response is None:
                self.logger.warning(f"Skipping Dubizzle page {page_num} ({listing_type})")
                break
            page_listings = self._parse_page(response.text, listing_type)
            if not page_listings:
                self.logger.info(f"No listings on page {page_num}, stopping")
                break
            all_listings.extend(page_listings)
            self.logger.info(f"  Page {page_num}: {len(page_listings)} listings")
            self.delay()
        return all_listings

    def _parse_page(self, html: str, listing_type: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        # <article> tags are the stable card wrapper on Dubizzle
        cards = soup.find_all("article")
        return [
            listing
            for card in cards
            if (listing := self._parse_card(card, listing_type))
        ]

    def _parse_card(self, card, listing_type: str) -> dict | None:
        try:
            # ── Title (from h2, strip Arabic half if bilingual) ────────────────
            h2 = card.find("h2")
            title = h2.get_text(strip=True) if h2 else None
            # Dubizzle titles are often "English Title - Arabic Title"
            # Keep only the English part before the dash
            if title and " - " in title:
                title = title.split(" - ")[0].strip()

            # ── Full text for regex parsing ────────────────────────────────────
            full_text = card.get_text(" ", strip=True)

            # ── Price (ر. ع = OMR in Arabic) ──────────────────────────────────
            price_match = re.search(r"([\d,]+)\s*ر\.\s*ع", full_text)
            if price_match:
                amount = price_match.group(1).replace(",", "")
                # detect frequency from Arabic words
                if "شهرياً" in full_text or "شهري" in full_text:
                    freq = "/ month"
                elif "سنوياً" in full_text or "سنوي" in full_text:
                    freq = "/ year"
                else:
                    freq = ""
                price = f"OMR {amount} {freq}".strip()
            else:
                price = None

            # ── Size (متر مربع = square metres in Arabic) ─────────────────────
            size_sqft = None
            size_match = re.search(r"متر مربع\s*([\d,]+)|(\d[\d,]*)\s*(?:sqft|sq\.?\s*ft)", full_text)
            if size_match:
                raw = (size_match.group(1) or size_match.group(2) or "0").replace(",", "")
                sqm = float(raw)
                # Convert sq metres → sq feet (1 m² ≈ 10.764 sqft)
                size_sqft = int(sqm * 10.764) if sqm else None

            # ── Location: extract from title "... in Al Khuwair" pattern ──────
            location = None
            if title:
                loc_match = re.search(r"\bin\s+([A-Z][A-Za-z\s]+?)(?:\s*[-,]|$)", title)
                if loc_match:
                    location = loc_match.group(1).strip()

            # ── Listing URL ────────────────────────────────────────────────────
            link = card.find("a", href=True)
            if link:
                href = link["href"]
                listing_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
            else:
                listing_url = None

            # ── Beds / baths from English text ────────────────────────────────
            beds  = _extract_int(full_text, r"(\d+)\s*(?:bed|bedroom|BR)")
            baths = _extract_int(full_text, r"(\d+)\s*(?:bath|bathroom)")

            if not title and not price:
                return None

            return self.make_listing(
                title        = title,
                price        = price,
                location     = location,
                bedrooms     = beds,
                bathrooms    = baths,
                size_sqft    = size_sqft,
                listing_type = listing_type,
                listing_url  = listing_url,
            )
        except Exception as e:
            self.logger.debug(f"Failed to parse Dubizzle card: {e}")
            return None


def _extract_int(text: str, pattern: str) -> int | None:
    match = re.search(pattern, text, re.I)
    if match:
        return int(match.group(1).replace(",", ""))
    return None
