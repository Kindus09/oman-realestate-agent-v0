# scraper/omanreal_scraper.py
#
# Scrapes property listings from omanreal.com.
#
# How Omanreal works:
#   Omanreal.com is a small Omani listing site. The homepage uses hash-based
#   navigation (#Sale, #Rent tabs) which means it's a single-page app loaded
#   via JavaScript. Static URLs like /properties-for-sale/muscat return 404.
#
#   We use two approaches:
#     1. Homepage scrape: the initial HTML loads some featured listings in
#        hidden tab sections that are in the DOM (just CSS-hidden).
#     2. Direct property links: collect any /n/ or /property/ URLs visible
#        on the homepage and fetch them individually.

import re

from bs4 import BeautifulSoup

from config.settings import MAX_PAGES
from scraper.base_scraper import BaseScraper

OMANREAL_HOME = "https://www.omanreal.com/"
OMANREAL_BASE = "https://www.omanreal.com"


class OmanrealScraper(BaseScraper):

    def __init__(self):
        super().__init__(name="omanreal")

    def scrape(self) -> list[dict]:
        # Fetch the homepage
        response = self.get(OMANREAL_HOME)
        if response is None:
            self.logger.warning("Could not reach omanreal.com — skipping")
            return []

        soup = BeautifulSoup(response.text, "lxml")

        # ── Approach 1: parse visible/hidden listing cards on the homepage ────
        listings = self._parse_homepage(soup)

        # ── Approach 2: follow property detail links ───────────────────────────
        property_urls = self._collect_property_links(soup)
        self.logger.info(f"Omanreal: {len(property_urls)} detail page links found")

        for url in property_urls[:MAX_PAGES * 5]:   # reasonable cap
            detail = self._scrape_detail(url)
            if detail:
                listings.append(detail)
            self.delay()

        return listings

    def _parse_homepage(self, soup: BeautifulSoup) -> list[dict]:
        """
        Extract whatever listing cards are in the initial DOM.
        Omanreal renders some cards in hidden tab panels (display:none in CSS).
        BeautifulSoup doesn't execute CSS so we can still read them.
        """
        listings = []

        # Common card selectors for small real estate sites
        cards = (
            soup.find_all("div", class_=re.compile(r"property.?card|listing.?item|prop.?box", re.I)) or
            soup.find_all("article") or
            soup.find_all("div", class_=re.compile(r"card", re.I))
        )

        for card in cards:
            text = card.get_text(" ", strip=True)
            if len(text) < 20:   # skip empty placeholder divs
                continue
            listing = self._parse_card(card)
            if listing:
                listings.append(listing)

        return listings

    def _collect_property_links(self, soup: BeautifulSoup) -> list[str]:
        """Find links to individual property/listing pages."""
        seen = set()
        urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            full = href if href.startswith("http") else f"{OMANREAL_BASE}{href}"
            if (
                "omanreal.com" in full
                and any(p in full for p in ("/n/", "/property/", "/listing/", "/ad/"))
                and full not in seen
            ):
                seen.add(full)
                urls.append(full)
        return urls

    def _parse_card(self, card) -> dict | None:
        try:
            title_el = card.find("h2") or card.find("h3") or card.find(class_=re.compile(r"title|name", re.I))
            title = title_el.get_text(strip=True) if title_el else None

            price_el = card.find(class_=re.compile(r"price|amount|omr", re.I))
            price = price_el.get_text(strip=True) if price_el else None

            loc_el = card.find(class_=re.compile(r"location|area|address", re.I))
            location = loc_el.get_text(strip=True) if loc_el else None

            link_el = card.find("a", href=True)
            if link_el:
                href = link_el["href"]
                listing_url = href if href.startswith("http") else f"{OMANREAL_BASE}{href}"
            else:
                listing_url = None

            text = card.get_text(" ", strip=True)
            listing_type = _detect_type(text)
            beds  = _extract_int(text, r"(\d+)\s*(?:bed|bedroom|BR)")
            baths = _extract_int(text, r"(\d+)\s*bath")

            if not title and not price:
                return None

            return self.make_listing(
                title        = title,
                price        = price,
                location     = location,
                bedrooms     = beds,
                bathrooms    = baths,
                listing_type = listing_type,
                listing_url  = listing_url,
            )
        except Exception as e:
            self.logger.debug(f"Omanreal card parse failed: {e}")
            return None

    def _scrape_detail(self, url: str) -> dict | None:
        response = self.get(url)
        if response is None:
            return None
        soup = BeautifulSoup(response.text, "lxml")
        try:
            title_el = soup.find("h1") or soup.find("h2")
            title = title_el.get_text(strip=True) if title_el else None

            price_el = soup.find(class_=re.compile(r"price|amount|omr", re.I))
            price = price_el.get_text(strip=True) if price_el else None

            loc_el = soup.find(class_=re.compile(r"location|address|area", re.I))
            location = loc_el.get_text(strip=True) if loc_el else None

            text = soup.get_text(" ", strip=True)
            listing_type = _detect_type(text)
            beds  = _extract_int(text, r"(\d+)\s*(?:bed|bedroom|BR)")
            baths = _extract_int(text, r"(\d+)\s*bath")
            size  = _extract_int(text, r"([\d,]+)\s*(?:sqft|sq\.?\s*ft)")

            return self.make_listing(
                title        = title,
                price        = price,
                location     = location,
                bedrooms     = beds,
                bathrooms    = baths,
                size_sqft    = size,
                listing_type = listing_type,
                listing_url  = url,
            )
        except Exception as e:
            self.logger.debug(f"Omanreal detail parse failed {url}: {e}")
            return None


def _detect_type(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ("rent", "lease", "monthly")): return "rent"
    if any(w in t for w in ("sale", "buy", "freehold")):  return "sale"
    return "unknown"

def _extract_int(text: str, pattern: str) -> int | None:
    m = re.search(pattern, text, re.I)
    return int(m.group(1).replace(",", "")) if m else None
