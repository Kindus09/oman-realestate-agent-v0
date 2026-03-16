# config/settings.py
# Central configuration for the Oman Real Estate Agent.
# Change values here instead of hunting through code.

import os
from pathlib import Path

# ─── Project root ─────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

# ─── Output file paths ────────────────────────────────────────────────────────
RAW_DATA_FILE = DATA_DIR / "raw_listings.json"       # merged output from all scrapers
CLEAN_DATA_FILE = DATA_DIR / "clean_listings.json"   # normalized, deduplicated

# ─── Scraper behaviour ────────────────────────────────────────────────────────
REQUEST_DELAY_MIN = 2   # seconds to wait between requests (lower bound)
REQUEST_DELAY_MAX = 3   # seconds to wait between requests (upper bound)
MAX_PAGES = 5           # how many listing pages to scrape per site (per listing type)
REQUEST_TIMEOUT = 30    # seconds before a request is considered failed

# HTTP headers sent with every request.
# A realistic User-Agent reduces the chance of being blocked.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─── Site URLs ────────────────────────────────────────────────────────────────
# Each entry is (sale_url_template, rent_url_template).
# Use {page} as a placeholder where pagination is needed.
# None means the site doesn't support that listing type (or uses the same URL).

BAYUT_SALE_URL   = "https://www.bayut.com/for-sale/property/oman/muscat/?page={page}"
BAYUT_RENT_URL   = "https://www.bayut.com/to-rent/property/oman/muscat/?page={page}"

# OpenSooq: /en/real-estate lists all property classifieds; page param is ?page=N
OPENSOOQ_URL     = "https://om.opensooq.com/en/real-estate?page={page}"

# Dubizzle Oman: correct URL structure uses /properties/ prefix
DUBIZZLE_SALE_URL = "https://www.dubizzle.com.om/properties/properties-for-sale/?page={page}"
DUBIZZLE_RENT_URL = "https://www.dubizzle.com.om/properties/properties-for-rent/?page={page}"

# Savills only lists rentals in their Muscat section
SAVILLS_RENT_URL  = "https://search.savills.com/om/en/list/property-to-rent/oman/muscat?page={page}"

# Tibiaan: uses WordPress ?paged= pagination on the homepage
TIBIAAN_URL       = "https://tibiaan.com/?paged={page}"

# Vista Oman: WordPress site with AJAX-loaded listings; we use their REST API
VISTAOMAN_API_URL = "https://vistaoman.com/wp-admin/admin-ajax.php"
VISTAOMAN_URL     = "https://vistaoman.com/property-type/apartments-flat-oman/page/{page}/"

# ─── Claude / Agent settings ──────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-opus-4-6"   # model used for the conversational agent
MAX_TOKENS        = 4096                # max tokens in a single Claude response

# ─── Muscat area name aliases ─────────────────────────────────────────────────
# Maps common misspellings / alternate spellings → canonical name.
# The data_cleaner uses this to normalise the location field.
AREA_ALIASES = {
    "al khuwair": "Al Khuwair",
    "khuwair":    "Al Khuwair",
    "al khwair":  "Al Khuwair",
    "bausher":    "Bausher",
    "bowsher":    "Bausher",
    "al bausher": "Bausher",
    "madinat al sultan qaboos": "MQ",
    "madinat sultan qaboos":    "MQ",
    "msq":                      "MQ",
    "mq":                       "MQ",
    "al mouj":   "The Wave",
    "mouj":      "The Wave",
    "the wave":  "The Wave",
    "qurum":     "Qurm",
    "qurm":      "Qurm",
    "al qurm":   "Qurm",
    "ghala":     "Ghala",
    "al ghala":  "Ghala",
    "ruwi":      "Ruwi",
    "al ruwi":   "Ruwi",
    "muttrah":   "Muttrah",
    "mutrah":    "Muttrah",
    "azaiba":    "Azaiba",
    "al azaiba": "Azaiba",
    "seeb":      "Seeb",
    "al seeb":   "Seeb",
    "amerat":    "Amerat",
    "al amerat": "Amerat",
    "darsait":   "Darsait",
    "wadi kabir":"Wadi Kabir",
    "al wadi al kabir": "Wadi Kabir",
    "shatti al qurum":  "Shatti Al Qurm",
    "shatti al qurm":   "Shatti Al Qurm",
    "al hail":   "Al Hail",
    "hail":      "Al Hail",
    "muscat hills": "Muscat Hills",
    "ansab":     "Ansab",
    "al ansab":  "Ansab",
}
