# scraper/data_cleaner.py
#
# Cleans and normalises the raw scraped data produced by runner.py.
#
# Run this after the scraper:
#   python -m scraper.data_cleaner
#
# What it does:
#   1. Loads data/raw_listings.json.
#   2. Normalises prices → numeric OMR value + frequency string.
#   3. Normalises location/area names using the alias map in settings.py.
#   4. Fills in listing_type where it's "unknown" using title heuristics.
#   5. Removes duplicate listings (same URL or very similar title+price+location).
#   6. Drops listings with no title and no price (empty/junk rows).
#   7. Saves data/clean_listings.json.

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import RAW_DATA_FILE, CLEAN_DATA_FILE, AREA_ALIASES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [cleaner] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("cleaner")


# ─── Price normalisation ───────────────────────────────────────────────────────

def parse_price(raw: str | None) -> dict:
    """
    Parse a raw price string into structured components.

    Returns a dict:
      {
        "price_omr":   float | None,   # numeric value in OMR
        "price_raw":   str,            # original string (kept for reference)
        "frequency":   str | None,     # "month", "year", "week", None (for sale)
      }

    Examples handled:
      "OMR 450 / month"  → {"price_omr": 450.0, "frequency": "month"}
      "450,000 OMR"      → {"price_omr": 450000.0, "frequency": None}
      "RO 1,200"         → {"price_omr": 1200.0, "frequency": None}
      "BD 2500"          → {"price_omr": None, ...}  (non-OMR currency)
    """
    result = {"price_omr": None, "price_raw": raw, "frequency": None}

    if not raw:
        return result

    text = raw.upper()

    # Detect frequency (for rentals).
    freq = None
    if re.search(r"\b(PER\s+)?MONTH\b|/\s*MONTH|MONTHLY|PCM", text):
        freq = "month"
    elif re.search(r"\b(PER\s+)?YEAR\b|/\s*YEAR|ANNUAL|YEARLY", text):
        freq = "year"
    elif re.search(r"\b(PER\s+)?WEEK\b|/\s*WEEK|WEEKLY", text):
        freq = "week"
    result["frequency"] = freq

    # Only parse OMR / RO prices (Rial Omani).
    # Skip if it's clearly a different currency (AED, USD, BD, etc.).
    non_omr = re.search(r"\b(AED|USD|USD|\$|BD|BHD|SAR|KWD|QAR)\b", text)
    if non_omr:
        return result

    # Extract the numeric value — handle commas as thousands separators.
    num_match = re.search(r"[\d,]+(?:\.\d+)?", raw.replace(",", ""))
    if num_match:
        try:
            result["price_omr"] = float(num_match.group().replace(",", ""))
        except ValueError:
            pass

    return result


# ─── Location normalisation ────────────────────────────────────────────────────

def normalise_location(raw: str | None) -> str | None:
    """
    Map location strings to canonical area names using AREA_ALIASES.
    The comparison is case-insensitive; we check whether any alias appears
    as a substring of the raw location string.
    """
    if not raw:
        return raw

    lower = raw.lower().strip()

    # Direct lookup first.
    if lower in AREA_ALIASES:
        return AREA_ALIASES[lower]

    # Substring match — useful for strings like "Al Khuwair, Muscat, Oman".
    for alias, canonical in AREA_ALIASES.items():
        if alias in lower:
            return canonical

    # Return the cleaned original if no alias matched.
    # Capitalise each word for consistency.
    return raw.strip().title()


# ─── Listing type repair ───────────────────────────────────────────────────────

def repair_listing_type(listing: dict) -> str:
    """
    If listing_type is "unknown", try to infer it from the title, price string,
    or listing URL.
    """
    lt = listing.get("listing_type", "unknown")
    if lt not in ("unknown", None, ""):
        return lt

    text = " ".join([
        listing.get("title") or "",
        listing.get("price_raw") or listing.get("price") or "",
        listing.get("listing_url") or "",
        listing.get("description") or "",
    ]).lower()

    if any(w in text for w in ("rent", "lease", "to-rent", "to_rent", "monthly", "per month")):
        return "rent"
    if any(w in text for w in ("sale", "buy", "for-sale", "for_sale", "freehold")):
        return "sale"
    return "unknown"


# ─── Deduplication ────────────────────────────────────────────────────────────

def make_fingerprint(listing: dict) -> str:
    """
    Create a deduplication key.
    Two listings are considered duplicates if they share the same URL,
    OR the same (title, price_omr, location) combination.
    """
    url   = (listing.get("listing_url") or "").strip().lower().rstrip("/")
    title = re.sub(r"\s+", " ", (listing.get("title") or "").lower().strip())
    price = str(listing.get("price_omr") or "")
    loc   = (listing.get("location") or "").lower().strip()

    if url:
        return f"url::{url}"
    return f"tlp::{title}|{price}|{loc}"


def deduplicate(listings: list[dict]) -> list[dict]:
    """Remove duplicates, keeping the first occurrence."""
    seen = set()
    unique = []
    for listing in listings:
        fp = make_fingerprint(listing)
        if fp not in seen:
            seen.add(fp)
            unique.append(listing)
    return unique


# ─── Main cleaning pipeline ───────────────────────────────────────────────────

def clean(listings: list[dict]) -> list[dict]:
    """Apply all cleaning steps to a list of raw listing dicts."""
    cleaned = []

    for raw in listings:
        # Step 1: drop junk rows (no title AND no price).
        if not raw.get("title") and not raw.get("price"):
            continue

        # Step 2: parse price.
        price_info = parse_price(raw.get("price"))

        # Step 3: normalise location.
        location = normalise_location(raw.get("location"))

        # Step 4: build the cleaned record.
        record = {
            **raw,                              # keep all original fields
            "location":    location,
            "price_raw":   raw.get("price"),    # preserve original price string
            "price_omr":   price_info["price_omr"],
            "frequency":   price_info["frequency"],
        }
        # Remove the old "price" key to avoid confusion — use price_raw / price_omr.
        record.pop("price", None)

        # Step 5: repair listing_type.
        record["listing_type"] = repair_listing_type(record)

        cleaned.append(record)

    # Step 6: deduplicate.
    before = len(cleaned)
    cleaned = deduplicate(cleaned)
    removed = before - len(cleaned)
    if removed:
        logger.info(f"Removed {removed} duplicate listings")

    return cleaned


# ─── I/O ──────────────────────────────────────────────────────────────────────

def load_raw() -> list[dict]:
    path = Path(RAW_DATA_FILE)
    if not path.exists():
        logger.error(f"Raw data file not found: {path}")
        logger.error("Run the scraper first:  python -m scraper.runner")
        sys.exit(1)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    # Support both a plain list and the metadata-envelope format from runner.py.
    if isinstance(data, list):
        return data
    return data.get("listings", [])


def save_clean(listings: list[dict]) -> None:
    path = Path(CLEAN_DATA_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(listings, f, ensure_ascii=False, indent=2)

    logger.info(f"Saved {len(listings)} clean listings → {path}")


def main():
    logger.info("Loading raw listings …")
    raw = load_raw()
    logger.info(f"Loaded {len(raw)} raw listings")

    logger.info("Cleaning …")
    clean_listings = clean(raw)
    logger.info(f"Clean listings: {len(clean_listings)}")

    # Print a quick breakdown by source and listing type.
    from collections import Counter
    by_source = Counter(l.get("source", "unknown") for l in clean_listings)
    by_type   = Counter(l.get("listing_type", "unknown") for l in clean_listings)
    logger.info(f"By source: {dict(by_source)}")
    logger.info(f"By type:   {dict(by_type)}")

    save_clean(clean_listings)


if __name__ == "__main__":
    main()
