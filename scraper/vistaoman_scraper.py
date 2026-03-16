# scraper/vistaoman_scraper.py
#
# Scrapes apartment/flat listings from Vista Oman.
# Target: https://vistaoman.com/property-type/apartments-flat-oman/
#
# How Vista Oman works:
#   Vista Oman runs on WordPress with a custom real estate theme (MyHome).
#   The listing grid is loaded via AJAX (admin-ajax.php) so the initial HTML
#   has no property cards.
#
#   However, individual property pages ARE server-rendered.
#   Strategy (same as Tibiaan):
#     1. Collect property URLs from the category page using the visible links.
#     2. If AJAX is needed, POST to admin-ajax.php with the right action.
#     3. Fetch each property page and parse.
#
#   All Vista Oman listings in the apartment section include both sale & rent.
#   We detect listing type from the page text.

import re

from bs4 import BeautifulSoup

from config.settings import VISTAOMAN_URL, VISTAOMAN_API_URL, MAX_PAGES
from scraper.base_scraper import BaseScraper


class VistaOmanScraper(BaseScraper):

    BASE_URL = "https://vistaoman.com"

    def __init__(self):
        super().__init__(name="vistaoman")

    def scrape(self) -> list[dict]:
        property_urls = self._collect_urls()
        self.logger.info(f"Vista Oman: found {len(property_urls)} property URLs")

        listings = []
        for i, url in enumerate(property_urls, start=1):
            listing = self._scrape_property(url)
            if listing:
                listings.append(listing)
            if i < len(property_urls):
                self.delay()

        return listings

    def _collect_urls(self) -> list[str]:
        """
        Collect property URLs from:
          1. The category page (links to individual properties)
          2. AJAX endpoint (POST to admin-ajax.php)
        """
        seen = set()
        urls = []

        for page_num in range(1, MAX_PAGES + 1):
            page_url = VISTAOMAN_URL.format(page=page_num)
            response = self.get(page_url)
            if response is None:
                break

            soup = BeautifulSoup(response.text, "lxml")
            new_found = self._extract_property_links(soup, seen, urls)
            self.logger.info(f"  Page {page_num}: {new_found} new property URLs")

            if new_found == 0:
                break
            self.delay()

        # Fallback: try AJAX endpoint used by the WordPress theme
        if not urls:
            urls = self._try_ajax_endpoint(seen)

        return urls

    def _extract_property_links(self, soup: BeautifulSoup, seen: set, urls: list) -> int:
        """Find links to individual property pages and add new ones to urls."""
        count = 0
        for a in soup.find_all("a", href=True):
            href = a["href"]
            # Vista Oman property pages are at /property/<slug>/ or /listing/<slug>/
            if (
                self.BASE_URL in href
                and any(p in href for p in ("/property/", "/listing/", "/estate/"))
                and href not in seen
                and not any(w in href for w in ("/property-type/", "/category/", "/tag/"))
            ):
                seen.add(href)
                urls.append(href)
                count += 1
        return count

    def _try_ajax_endpoint(self, seen: set) -> list[str]:
        """
        POST to the WordPress AJAX endpoint used by the MyHome theme
        to load property listings dynamically.
        """
        urls = []
        try:
            # MyHome theme action for loading properties
            payload = {
                "action":         "myhome_get_estates",
                "per_page":       "20",
                "page":           "1",
                "status[]":       ["for-rent", "for-sale"],
                "location_slug":  "muscat",
            }
            response = self.session.post(
                VISTAOMAN_API_URL,
                data=payload,
                timeout=20,
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")
            self._extract_property_links(soup, seen, urls)
            self.logger.info(f"AJAX endpoint returned {len(urls)} URLs")
        except Exception as e:
            self.logger.debug(f"Vista Oman AJAX endpoint failed: {e}")
        return urls

    def _scrape_property(self, url: str) -> dict | None:
        """Fetch and parse a single Vista Oman property detail page."""
        response = self.get(url)
        if response is None:
            return None

        soup = BeautifulSoup(response.text, "lxml")

        try:
            # ── Title ──────────────────────────────────────────────────────────
            title_el = soup.find("h1") or soup.find("h2")
            title = title_el.get_text(strip=True) if title_el else None

            # ── Price ──────────────────────────────────────────────────────────
            price_el = soup.find(class_=re.compile(r"price|amount|omr|cost", re.I))
            price = price_el.get_text(strip=True) if price_el else None

            # ── Location ───────────────────────────────────────────────────────
            loc_el = soup.find(class_=re.compile(r"location|address|area|city", re.I))
            location = loc_el.get_text(strip=True) if loc_el else None

            # Try extracting location from title "... in Al Khuwair" pattern
            if not location and title:
                m = re.search(r"\bin\s+([A-Z][A-Za-z\s]+?)(?:\s*[-,]|$)", title)
                if m:
                    location = m.group(1).strip()

            page_text = soup.get_text(" ", strip=True)

            # ── Listing type ───────────────────────────────────────────────────
            if any(w in page_text.lower() for w in ("for rent", "to rent", "rental", "monthly")):
                listing_type = "rent"
            elif any(w in page_text.lower() for w in ("for sale", "freehold")):
                listing_type = "sale"
            else:
                listing_type = _detect_from_url(url)

            # ── Property type ──────────────────────────────────────────────────
            property_type = "apartment"   # default for this category
            for ptype in ("villa", "townhouse", "penthouse", "studio", "duplex"):
                if ptype in page_text.lower():
                    property_type = ptype
                    break

            # ── Beds / baths / size ────────────────────────────────────────────
            beds  = _extract_int(page_text, r"(\d+)\s*(?:bed|bedroom|BHK|BR)")
            baths = _extract_int(page_text, r"(\d+)\s*bath")
            sqm   = _extract_float(page_text, r"([\d.]+)\s*(?:sqm|m²|sq\.?\s*m)")
            sqft  = _extract_int(page_text, r"([\d,]+)\s*(?:sqft|sq\.?\s*ft)")
            size_sqft = int(sqm * 10.764) if sqm else sqft

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
            self.logger.debug(f"Failed to parse Vista Oman page {url}: {e}")
            return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _detect_from_url(url: str) -> str:
    u = url.lower()
    if "rent" in u:  return "rent"
    if "sale" in u:  return "sale"
    return "unknown"

def _extract_int(text: str, pattern: str) -> int | None:
    m = re.search(pattern, text, re.I)
    if m:
        return int(m.group(1).replace(",", ""))
    return None

def _extract_float(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text, re.I)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None
