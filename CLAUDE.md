# CLAUDE.md — Oman Real Estate Agent

This file tells Claude Code how to work on this project.

---

## What This Project Is

A conversational AI agent for the Muscat, Oman property market. It scrapes
listings from 7 real estate websites, cleans the data, and exposes it through
a Claude-powered chat interface. Users ask natural-language questions ("what's
a typical 3-bedroom rent in Al Khuwair?") and the agent queries the local data
using Claude function-calling tools to answer them.

---

## Architecture

```
Scraper layer          →   Data layer            →   Agent layer          →   Interface layer
────────────────────────────────────────────────────────────────────────────────────────────
7 site scrapers        →   data/raw_listings.json
     ↓                          ↓
 runner.py             →   data_cleaner.py       →   data/clean_listings.json
                                                            ↓
                                                     agent/tools.py  (4 tools)
                                                            ↓
                                                     agent/main.py   (CLI loop) ← python -m agent.main
                                                            ↓
                                                      Claude API
                                                      (tool_use)
                                                            ↓
                                                     bot/telegram_bot.py  ← Telegram users
```

### Scraper layer (`scraper/`)
- `base_scraper.py` — abstract `BaseScraper` class. Handles the requests
  session, polite delays, logging, and the shared `make_listing()` helper.
  Every site scraper inherits this. Do not add site-specific logic here.
- `bayut_scraper.py` — Bayut.com/oman. Currently blocked by JS bot challenge.
  Scraper is ready; just returns 0 until a headless browser is added.
- `opensooq_scraper.py` — om.opensooq.com. Parses `<a class="postItem">`
  cards with structured `data-*` attributes. **198 listings/page, most
  productive source.**
- `dubizzle_scraper.py` — dubizzle.com.om. Uses hashed CSS classes; parsing
  uses regex on full text + h2. URLs: `/properties/properties-for-{rent,sale}/`.
- `savills_scraper.py` — search.savills.com. Rent-only. Fetches 2 listings/page
  but they deduplicate to 0 after cleaning (insufficient data in HTML).
- `tibiaan_scraper.py` — tibiaan.com. JS-rendered grid; strategy is to collect
  property URLs from `/?paged=N` pages then fetch each individually.
- `vistaoman_scraper.py` — vistaoman.com. WordPress + MyHome theme with
  AJAX-loaded listings. Tries the REST API and AJAX endpoint; currently 0 results.
- `omanreal_scraper.py` — omanreal.com. SPA with hash routing. Scrapes homepage
  DOM and follows detail links; very few results.
- `runner.py` — runs all 7 scrapers sequentially, saves `data/raw_listings.json`
  with a metadata envelope (`scraped_at`, `total_listings`, `listings`).
- `data_cleaner.py` — normalises OMR prices to numeric, maps area aliases to
  canonical names, deduplicates by URL fingerprint or title+price+location,
  saves `data/clean_listings.json`.

### Agent layer (`agent/`)
- `models.py` — Pydantic models: `Property`, `SearchFilters`, `SearchResult`,
  `AreaStats`. `Property.summary()` produces a one-line display string.
- `tools.py` — four tool functions + their JSON schemas for Claude:
  - `search_listings` — filter by type/area/price/beds/property_type/source
  - `get_area_stats` — avg/min/max price + bedroom stats for an area
  - `get_price_range` — price range for a listing type + bedroom count
  - `list_areas` — all unique area names in the data
  - `dispatch_tool()` — routes Claude tool_use blocks to the right function
  - `load_listings()` — loads and caches `clean_listings.json` at startup
- `prompts.py` — system prompt. Defines the agent persona, lists the 7 data
  sources, explains the tools, and sets tone/behaviour guidelines.
- `main.py` — CLI agentic loop. Loads data → initialises Claude client →
  runs the tool-use loop (up to 5 iterations per turn) → prints reply.

### Bot layer (`bot/`)
- `telegram_bot.py` — pure transport layer. Receives Telegram messages, passes
  them to `run_agent_turn()` from `agent/main.py`, sends the reply back.
  No agent logic lives here.
- Uses `python-telegram-bot` v20+ (fully async, `Application` builder pattern).
- Per-user conversation history stored in `USER_HISTORIES: dict[int, list[dict]]`
  keyed by Telegram user_id. In-memory only — cleared on bot restart.
- The synchronous Anthropic SDK call is wrapped in `asyncio.to_thread()` to
  avoid blocking the async event loop.
- Handles Telegram's 4096-char limit via `send_long_message()` + `_split_text()`.
- Commands: `/start` (new session), `/help` (capabilities), `/clear` (reset history).
- Run with: `python -m bot.telegram_bot` (requires `TELEGRAM_BOT_TOKEN` in `.env`)

### Config (`config/`)
- `settings.py` — single source of truth for all magic values: site URLs,
  request delays, page limits, file paths, Claude model, area alias map.
  Change values here, not scattered through scraper files.

### Tests (`tests/`)
- `test_base_scraper.py` — 7 tests for `BaseScraper` helpers
- `test_data_cleaner.py` — 20 tests for price parsing, location normalisation,
  deduplication
- `test_tools.py` — 21 tests for all 4 agent tools using injected fake listings
- **53 tests, all passing.** Run with: `python -m pytest tests/ -v`

---

## Tech Stack

| Concern | Library |
|---|---|
| HTTP requests | `requests` |
| HTML parsing | `beautifulsoup4` + `lxml` |
| Data validation | `pydantic` v2 |
| Claude API | `anthropic` SDK |
| Telegram bot | `python-telegram-bot` v20+ |
| Environment vars | `python-dotenv` |
| Tests | `pytest` |
| Python version | 3.14 (Windows) |

No database. Data lives in flat JSON files. Async only in the Telegram bot layer.

---

## Current Data Status (as of last run)

| Site | Raw listings | After cleaning |
|---|---|---|
| OpenSooq | 990 | 289 |
| Dubizzle | 450 | 342 |
| Tibiaan | 6 | 6 |
| Savills | 10 | 0 (deduped out — too little data) |
| Omanreal | 1 | 0 (deduped out) |
| Bayut | 0 | 0 (bot-blocked) |
| Vista Oman | 0 | 0 (JS-rendered) |
| **Total** | **1,457** | **637** |

Data covers: 637 Muscat listings across 83 areas, split ~295 sale / 342 rent.

---

## Known Gaps

### Bayut (biggest gap)
Bayut is the dominant Oman real estate portal but blocks plain HTTP requests
with a JavaScript challenge. Fix options:
- Add Playwright: `pip install playwright && playwright install chromium`
- Use a proxy API (ScraperAPI, Zyte) that handles JS challenges
- The scraper code is already written — just swap `self.get()` for a
  headless browser call in `bayut_scraper.py`

### Vista Oman
WordPress site with AJAX-loaded listings. The AJAX endpoint (`admin-ajax.php`)
returns 404 for our POST payload. Need to reverse-engineer the exact request
the browser makes (check Network tab → XHR calls on the listings page).

### Savills
Only ~10 listings in Muscat, and the HTML cards don't carry enough data to
survive deduplication. Low priority — small inventory.

### Arabic content in Dubizzle
Dubizzle Oman serves Arabic content. Titles are bilingual ("English — Arabic").
The scraper strips the Arabic half, but price/size parsing relies on Arabic
characters (ر. ع for OMR, متر مربع for sqm). If Dubizzle changes their Arabic
formatting, these regex patterns in `dubizzle_scraper.py` will break.

### No session persistence
Each `python -m agent.main` session starts fresh. There is no conversation
history saved between runs.

### Windows terminal encoding
The Windows cp1252 terminal cannot display Arabic characters or Unicode
box-drawing characters. The agent and runner log in ASCII-safe format.
If adding new print statements, avoid Unicode symbols.

### Data freshness
Data is scraped once manually. There is no scheduler or auto-refresh.
Re-run `python -m scraper.runner` then `python -m scraper.data_cleaner`
whenever fresh data is needed.

---

## How to Run

```bash
# Install dependencies
pip install -r requirements.txt

# Set API key
copy .env.example .env   # then edit .env with your ANTHROPIC_API_KEY

# Scrape (takes ~2 mins with polite delays)
python -m scraper.runner

# Clean
python -m scraper.data_cleaner

# Chat (CLI)
python -m agent.main

# Telegram bot
python -m bot.telegram_bot   # requires TELEGRAM_BOT_TOKEN in .env

# Tests
python -m pytest tests/ -v
```

---

## Rules for Working on This Codebase

### General
- Always proceed without asking for confirmation — the user has set "always
  allow access" for this project.
- Run `python -m pytest tests/ -v` after any change to scraper or agent logic.
- Do not add new dependencies without updating `requirements.txt`.
- Do not create new files unless clearly necessary. Prefer editing existing ones.

### Scraper layer
- All configurable values (URLs, delays, page limits) belong in `config/settings.py`.
  Never hardcode URLs or magic numbers in scraper files.
- Every scraper must inherit `BaseScraper` and call `self.make_listing(**kwargs)`
  to build listing dicts. Never construct raw dicts manually.
- Every scraper must call `self.delay()` between page requests.
- Do not add site-specific logic to `base_scraper.py`.
- When fixing a scraper, first fetch the live page and inspect the actual HTML
  before changing selectors — sites change structure frequently.
- CSS class names on Dubizzle are hashed and will change. Never rely on them.
  Use tag-type selectors (`article`, `h2`) and full-text regex instead.

### Data cleaner
- `parse_price()`, `normalise_location()`, `repair_listing_type()`, and
  `deduplicate()` are the four cleaning functions. Keep them pure (no I/O,
  no side effects) so the tests stay fast.
- New area aliases go in `config/settings.py → AREA_ALIASES`, not in
  `data_cleaner.py`.

### Agent layer
- New tools must be added in three places: the Python function in `tools.py`,
  the JSON schema in `TOOL_DEFINITIONS`, and the routing in `dispatch_tool()`.
- Do not change `CLAUDE_MODEL` in `settings.py` without testing — the tool_use
  schema format must be compatible with the chosen model.
- The agentic loop in `main.py` is capped at 5 iterations per turn to prevent
  infinite loops. Do not remove this cap.
- Keep `prompts.py` honest — only list tools and data sources that actually exist.

### Bot layer
- `bot/telegram_bot.py` is a transport layer only. Do not add agent logic here.
  All reasoning stays in `agent/main.py`.
- `USER_HISTORIES` is in-memory. Restoring or persisting history across restarts
  requires a database — do not add persistence hacks to the dict.
- The Anthropic SDK call must always run inside `asyncio.to_thread()`. Never
  call synchronous blocking functions directly in an async handler.
- `send_long_message()` handles Telegram's 4096-char limit. Do not bypass it.
- `TELEGRAM_BOT_TOKEN` must live in `.env`, never in code or `.env.example`.

### Tests
- Tests in `test_tools.py` inject fake listings via the `inject_listings`
  autouse fixture. Never let tests hit the real `clean_listings.json`.
- Tests must not make network requests. If adding scraper tests, mock `self.get()`.
- All 53 tests must pass before committing any change.
