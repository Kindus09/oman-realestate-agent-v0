# scraper/tibiaan_scraper.py
#
# Scrapes property listings from tibiaan.com — an Oman-focused real estate agency.
#
# How Tibiaan works:
#   Tibiaan's listing grid is rendered by JavaScript (templates are empty in HTML).
#   However, the homepage and paginated pages (?paged=N) contain direct links to
#   individual property pages (e.g. /property/villa-for-rent-in-al-khuwair).
#   These individual pages ARE fully server-rendered.
#
#   Strategy:
#     1. Fetch homepage pages (?paged=N) to collect property URLs.
#     2. Fetch each individual property page and parse the details.
#
#   The URL slug is also informative:
#     "villa-for-rent-in-al-khuwair"  →  type=villa, listing=rent, area=Al Khuwair
#   We use this as a quick fallback when the page parse fails.

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config.settings import TIBIAAN_URL, MAX_PAGES
from scraper.base_scraper import BaseScraper


class TibiaanScraper(BaseScraper):

    BASE_URL = "https://tibiaan.com"

    def __init__(self):
        super().__init__(name="tibiaan")

    def scrape(self) -> list[dict]:
        # Step 1: collect all property URLs from paginated listing pages
        property_urls = self._collect_property_urls()
        self.logger.info(f"Tibiaan: found {len(property_urls)} property URLs")

        # Step 2: fetch each property page and parse it
        listings = []
        for i, url in enumerate(property_urls, start=1):
            listing = self._scrape_property_page(url)
            if listing:
                listings.append(listing)
            # Delay every request, not just between pages
            if i < len(property_urls):
                self.delay()

        return listings

    def _collect_property_urls(self) -> list[str]:
        """
        Fetch paginated homepage/listing pages and collect unique property URLs.
        Property links match the pattern: /property/<slug>
        """
        seen = set()
        urls = []

        for page_num in range(1, MAX_PAGES + 1):
            # Page 1 is the homepage itself; subsequent pages use ?paged=N
            page_url = self.BASE_URL + "/" if page_num == 1 else TIBIAAN_URL.format(page=page_num)
            response = self.get(page_url)
            if response is None:
                break

            soup = BeautifulSoup(response.text, "lxml")

            # Find all links to /property/<slug> that are not social share links
            new_found = 0
            for a in soup.find_all("a", href=True):
                href = a["href"]
                # Must be a tibiaan property link, not a social media sharer
                if (
                    f"{self.BASE_URL}/property/" in href
                    and "facebook.com" not in href
                    and "twitter.com" not in href
                    and href not in seen
                ):
                    seen.add(href)
                    urls.append(href)
                    new_found += 1

            self.logger.info(f"  Page {page_num}: {new_found} new property URLs")
            if new_found == 0:
                break   # no new links — we've reached the end

            self.delay()

        return urls

    def _scrape_property_page(self, url: str) -> dict | None:
        """Fetch and parse a single Tibiaan property detail page."""
        response = self.get(url)
        if response is None:
            return None

        soup = BeautifulSoup(response.text, "lxml")

        try:
            # ── Title ──────────────────────────────────────────────────────────
            title_el = (
                soup.find("h1", class_=re.compile(r"title|heading|property", re.I)) or
                soup.find("h1") or
                soup.find("h2")
            )
            title = title_el.get_text(strip=True) if title_el else None

            # ── Price ──────────────────────────────────────────────────────────
            price_el = soup.find(class_=re.compile(r"price|amount|cost", re.I))
            price = price_el.get_text(strip=True) if price_el else None

            # ── Location ───────────────────────────────────────────────────────
            loc_el = soup.find(class_=re.compile(r"location|address|area", re.I))
            location = loc_el.get_text(strip=True) if loc_el else None

            # ── Listing type & property type from URL slug ─────────────────────
            # e.g. "villa-for-rent-in-al-khuwair" → rent, villa
            slug = url.rstrip("/").split("/")[-1].lower()
            listing_type  = "rent" if "for-rent" in slug else ("sale" if "for-sale" in slug else "unknown")
            property_type = _type_from_slug(slug)

            # If location not found in page, extract from slug: "...-in-al-khuwair"
            if not location:
                loc_match = re.search(r"-in-(.+)$", slug)
                if loc_match:
                    location = loc_match.group(1).replace("-", " ").title()

            # ── Beds / baths / size from page text ────────────────────────────
            page_text = soup.get_text(" ", strip=True)
            beds  = _extract_int(page_text, r"(\d+)\s*(?:bed|bedroom|BR|BHK)")
            baths = _extract_int(page_text, r"(\d+)\s*(?:bath|bathroom)")
            sqm   = _extract_float(page_text, r"([\d.]+)\s*(?:sqm|m²|sq\.?\s*m)")
            sqft_direct = _extract_int(page_text, r"([\d,]+)\s*(?:sqft|sq\.?\s*ft)")
            if sqm:
                size_sqft = int(sqm * 10.764)
            elif sqft_direct:
                size_sqft = sqft_direct
            else:
                size_sqft = None

            return self.make_listing(
                title         = title,
                price         = price,
                location      = location,
                bedrooms      = beds,
                bathrooms     = baths,
                size_sqft     = size_sqft,
                property_type = property_type,
                listing_type  = listing_type,
                listing_url   = url,
            )
        except Exception as e:
            self.logger.debug(f"Failed to parse Tibiaan property page {url}: {e}")
            return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _type_from_slug(slug: str) -> str | None:
    for ptype in ("villa", "apartment", "flat", "studio", "townhouse",
                  "penthouse", "shop", "office", "land", "warehouse"):
        if ptype in slug:
            return ptype
    return None

def _extract_int(text: str, pattern: str) -> int | None:
    m = re.search(pattern, text, re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    return None

def _extract_float(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text, re.I)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None
