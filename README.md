# Oman Real Estate Agent

A conversational AI agent for the Muscat, Oman property market.

Scrapes listings from 7 sites → cleans the data → lets you chat with Claude to find properties, compare areas, and understand prices.

## Project Structure

```
oman-realestate-agent-v0/
├── config/
│   └── settings.py          # All configurable values (URLs, delays, model, paths)
├── scraper/
│   ├── base_scraper.py      # Shared scraper logic (requests, delays, logging)
│   ├── bayut_scraper.py     # bayut.com/oman
│   ├── opensooq_scraper.py  # om.opensooq.com
│   ├── dubizzle_scraper.py  # dubizzle.com.om
│   ├── savills_scraper.py   # search.savills.com (rent only)
│   ├── tibiaan_scraper.py   # tibiaan.com
│   ├── vistaoman_scraper.py # vistaoman.com
│   ├── omanreal_scraper.py  # omanreal.com
│   ├── runner.py            # Runs all scrapers, saves raw_listings.json
│   └── data_cleaner.py      # Normalises prices/areas, deduplicates → clean_listings.json
├── agent/
│   ├── models.py            # Pydantic models: Property, SearchResult, AreaStats
│   ├── tools.py             # Tool functions + JSON schemas for Claude API
│   ├── prompts.py           # System prompt (agent persona + instructions)
│   └── main.py              # CLI chat loop
├── data/                    # JSON files land here (gitignored)
├── tests/
├── .env.example
├── .gitignore
└── requirements.txt
```

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your API key

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 3. Run the scraper

Scrapes all 7 sites (first 5 pages each) and saves raw data:

```bash
python -m scraper.runner
```

### 4. Clean the data

Normalises prices and area names, removes duplicates:

```bash
python -m scraper.data_cleaner
```

### 5. Start chatting

```bash
python -m agent.main
```

Example questions you can ask:
- "What are the cheapest 2-bedroom apartments for rent in Al Khuwair?"
- "How does pricing in Bausher compare to Shatti Al Qurm?"
- "Show me villas for sale under 200,000 OMR"
- "What's the average monthly rent for a studio in Muscat?"
- "Which areas have the most listings?"

## Data Sources

| Site | Listing Types | Notes |
|------|--------------|-------|
| [Bayut](https://www.bayut.com/oman/) | Sale + Rent | Uses Next.js embedded JSON |
| [OpenSooq](https://om.opensooq.com) | Sale + Rent | Classifieds style |
| [Dubizzle](https://www.dubizzle.com.om) | Sale + Rent | Next.js, sister site of Bayut |
| [Savills](https://search.savills.com/om/en/) | Rent only | International agency |
| [Tibiaan](https://www.tibiaan.com) | Sale + Rent | Local Oman portal |
| [Vista Oman](https://vistaoman.com) | Sale + Rent | WordPress-based |
| [Omanreal](https://www.omanreal.com) | Sale + Rent | Local portal |

## How the Agent Works

1. **Tool calling**: Claude receives a list of tool definitions (search_listings, get_area_stats, get_price_range, list_areas).
2. **Decision**: When you ask a question, Claude decides which tool(s) to call.
3. **Execution**: `agent/main.py` runs the tool function against the local JSON data.
4. **Response**: Claude reads the tool result and writes a natural-language answer.

## Updating the Data

Re-run steps 3 and 4 whenever you want fresh listings. The scraper is polite (2–3s delays) and starts with 5 pages per site — change `MAX_PAGES` in `config/settings.py` to scrape more.

## Notes for Learners

- Read `scraper/base_scraper.py` first — it's the foundation everything else builds on.
- `scraper/bayut_scraper.py` is the most detailed and well-commented scraper.
- `agent/tools.py` shows how to define Claude tools and wire them to Python functions.
- `agent/main.py` shows the full Claude tool-use agentic loop pattern.
