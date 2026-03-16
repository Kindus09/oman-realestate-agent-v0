# agent/tools.py
#
# Python functions that the Claude agent can call as "tools" (function calling).
#
# How Claude tool use works:
#   1. We tell Claude about these functions by passing their JSON schema in
#      the `tools` parameter of the API request.
#   2. When Claude wants to call a tool, it returns a response with
#      stop_reason="tool_use" and a list of tool calls.
#   3. We execute the matching Python function here and send the result back
#      to Claude as a "tool_result" message.
#   4. Claude reads the result and writes its final answer to the user.
#
# Each function below is paired with a `_schema_*` dict that describes it
# to Claude. The TOOL_DEFINITIONS list at the bottom bundles everything together.

from __future__ import annotations

import json
import logging
from typing import Any

from agent.models import Property, SearchFilters, SearchResult, AreaStats

logger = logging.getLogger(__name__)

# Module-level cache — listings are loaded once and reused across tool calls.
_listings_cache: list[Property] | None = None


# ─── Data loading ─────────────────────────────────────────────────────────────

def load_listings(filepath: str) -> list[Property]:
    """
    Load and parse clean_listings.json into a list of Property objects.
    Results are cached in memory so we only read the file once per session.
    """
    global _listings_cache
    if _listings_cache is not None:
        return _listings_cache

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    try:
        with open(filepath, encoding="utf-8") as f:
            raw = json.load(f)
        # Support both a plain list and a metadata envelope.
        items = raw if isinstance(raw, list) else raw.get("listings", [])
        _listings_cache = [Property(**item) for item in items]
        logger.info(f"Loaded {len(_listings_cache)} listings from {filepath}")
    except FileNotFoundError:
        logger.error(f"Listings file not found: {filepath}")
        logger.error("Run the scraper and cleaner first.")
        _listings_cache = []
    except Exception as e:
        logger.error(f"Failed to load listings: {e}")
        _listings_cache = []

    return _listings_cache


def _get_listings() -> list[Property]:
    """Internal helper — returns cached listings (must call load_listings first)."""
    if _listings_cache is None:
        raise RuntimeError("Listings not loaded. Call load_listings() first.")
    return _listings_cache


# ─── Tool implementations ─────────────────────────────────────────────────────

def search_listings(
    listing_type:  str | None  = None,
    location:      str | None  = None,
    min_price_omr: float | None = None,
    max_price_omr: float | None = None,
    min_bedrooms:  int | None  = None,
    max_bedrooms:  int | None  = None,
    property_type: str | None  = None,
    source:        str | None  = None,
    limit:         int         = 10,
) -> dict:
    """
    Search the property listings with optional filters.
    Returns a dict (Claude receives this as a JSON string).
    """
    listings = _get_listings()
    results  = listings  # start with all, then filter down

    # Apply each filter if provided.
    # str.lower() comparisons make matching case-insensitive.
    if listing_type:
        results = [l for l in results if (l.listing_type or "").lower() == listing_type.lower()]

    if location:
        loc_lower = location.lower()
        results = [l for l in results if loc_lower in (l.location or "").lower()]

    if min_price_omr is not None:
        results = [l for l in results if l.price_omr is not None and l.price_omr >= min_price_omr]

    if max_price_omr is not None:
        results = [l for l in results if l.price_omr is not None and l.price_omr <= max_price_omr]

    if min_bedrooms is not None:
        results = [l for l in results if l.bedrooms is not None and l.bedrooms >= min_bedrooms]

    if max_bedrooms is not None:
        results = [l for l in results if l.bedrooms is not None and l.bedrooms <= max_bedrooms]

    if property_type:
        pt_lower = property_type.lower()
        results = [l for l in results if pt_lower in (l.property_type or "").lower()]

    if source:
        results = [l for l in results if (l.source or "").lower() == source.lower()]

    total  = len(results)
    subset = results[:limit]

    search_result = SearchResult(
        total_found  = total,
        returned     = len(subset),
        filters_used = {
            "listing_type":  listing_type,
            "location":      location,
            "min_price_omr": min_price_omr,
            "max_price_omr": max_price_omr,
            "min_bedrooms":  min_bedrooms,
            "max_bedrooms":  max_bedrooms,
            "property_type": property_type,
            "source":        source,
            "limit":         limit,
        },
        listings = subset,
    )

    return search_result.model_dump()


def get_area_stats(area: str, listing_type: str = "all") -> dict:
    """
    Compute price and bedroom statistics for a given area.
    listing_type: "sale", "rent", or "all" (default).
    """
    listings = _get_listings()

    # Filter by area (partial, case-insensitive match).
    area_lower = area.lower()
    subset = [l for l in listings if area_lower in (l.location or "").lower()]

    # Filter by listing type if specified.
    if listing_type.lower() != "all":
        subset = [l for l in subset if (l.listing_type or "").lower() == listing_type.lower()]

    if not subset:
        return AreaStats(
            area=area, listing_type=listing_type, total_listings=0
        ).model_dump()

    # Compute statistics on listings that have a numeric price.
    prices = [l.price_omr for l in subset if l.price_omr is not None]
    beds   = [l.bedrooms  for l in subset if l.bedrooms  is not None]

    stats = AreaStats(
        area           = area,
        listing_type   = listing_type,
        total_listings = len(subset),
        avg_price_omr  = round(sum(prices) / len(prices), 2) if prices else None,
        min_price_omr  = min(prices) if prices else None,
        max_price_omr  = max(prices) if prices else None,
        avg_bedrooms   = round(sum(beds) / len(beds), 1) if beds else None,
        sources        = sorted(set(l.source for l in subset if l.source)),
    )
    return stats.model_dump()


def get_price_range(listing_type: str, bedrooms: int | None = None) -> dict:
    """
    Return the min/max/average OMR price across all Muscat listings,
    optionally filtered by listing type and bedroom count.
    Useful for answering "what's a typical rent for a 2-bed?"
    """
    listings = _get_listings()

    if listing_type.lower() != "all":
        listings = [l for l in listings if (l.listing_type or "").lower() == listing_type.lower()]

    if bedrooms is not None:
        listings = [l for l in listings if l.bedrooms == bedrooms]

    prices = [l.price_omr for l in listings if l.price_omr is not None]

    if not prices:
        return {
            "listing_type": listing_type,
            "bedrooms":     bedrooms,
            "count":        0,
            "min_omr":      None,
            "max_omr":      None,
            "avg_omr":      None,
        }

    return {
        "listing_type": listing_type,
        "bedrooms":     bedrooms,
        "count":        len(prices),
        "min_omr":      min(prices),
        "max_omr":      max(prices),
        "avg_omr":      round(sum(prices) / len(prices), 2),
    }


def list_areas() -> dict:
    """Return all unique area names found in the listings, sorted alphabetically."""
    listings = _get_listings()
    areas = sorted(set(
        l.location for l in listings
        if l.location and l.location.lower() not in ("", "oman", "muscat")
    ))
    return {"areas": areas, "total": len(areas)}


# ─── Tool schemas (JSON schema format for Claude API) ─────────────────────────
# These tell Claude what each tool does and what arguments it accepts.
# Claude uses these to decide when and how to call each tool.

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "search_listings",
        "description": (
            "Search Muscat real estate listings with optional filters. "
            "Use this to find properties matching a user's criteria such as "
            "budget, area, number of bedrooms, or listing type (sale/rent)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_type": {
                    "type": "string",
                    "enum": ["sale", "rent"],
                    "description": "Filter by sale or rent listings.",
                },
                "location": {
                    "type": "string",
                    "description": "Area or neighbourhood name, e.g. 'Al Khuwair', 'Bausher'. Partial match.",
                },
                "min_price_omr": {
                    "type": "number",
                    "description": "Minimum price in OMR (Omani Rial).",
                },
                "max_price_omr": {
                    "type": "number",
                    "description": "Maximum price in OMR.",
                },
                "min_bedrooms": {
                    "type": "integer",
                    "description": "Minimum number of bedrooms.",
                },
                "max_bedrooms": {
                    "type": "integer",
                    "description": "Maximum number of bedrooms.",
                },
                "property_type": {
                    "type": "string",
                    "description": "Property type, e.g. 'apartment', 'villa', 'studio'.",
                },
                "source": {
                    "type": "string",
                    "description": "Filter by data source site name, e.g. 'bayut', 'dubizzle'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return. Default: 10.",
                    "default": 10,
                },
            },
        },
    },
    {
        "name": "get_area_stats",
        "description": (
            "Get price statistics (average, min, max) and listing counts for a "
            "specific area in Muscat. Useful for questions like 'how expensive is "
            "Shatti Al Qurm?' or 'what's the average rent in Bausher?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "area": {
                    "type": "string",
                    "description": "Area name, e.g. 'Al Khuwair', 'The Wave'. Partial match.",
                },
                "listing_type": {
                    "type": "string",
                    "enum": ["sale", "rent", "all"],
                    "description": "Which listing type to include. Default: 'all'.",
                    "default": "all",
                },
            },
            "required": ["area"],
        },
    },
    {
        "name": "get_price_range",
        "description": (
            "Get the min/max/average price for a listing type and optional bedroom count "
            "across all Muscat listings. Good for answering 'what does a 2-bedroom "
            "apartment rent for?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "listing_type": {
                    "type": "string",
                    "enum": ["sale", "rent", "all"],
                    "description": "Listing type to analyse.",
                },
                "bedrooms": {
                    "type": "integer",
                    "description": "Filter by exact bedroom count, e.g. 2 for 2-bed properties.",
                },
            },
            "required": ["listing_type"],
        },
    },
    {
        "name": "list_areas",
        "description": (
            "Return all unique area/neighbourhood names found in the listing data. "
            "Useful when the user wants to know which areas are available or asks "
            "'what areas do you have data for?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


# ─── Tool dispatcher ──────────────────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_input: dict) -> Any:
    """
    Called by main.py when Claude returns a tool_use response.
    Routes the call to the correct Python function and returns the result.
    """
    TOOL_MAP = {
        "search_listings": search_listings,
        "get_area_stats":  get_area_stats,
        "get_price_range": get_price_range,
        "list_areas":      list_areas,
    }

    fn = TOOL_MAP.get(tool_name)
    if fn is None:
        logger.error(f"Unknown tool: {tool_name}")
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        return fn(**tool_input)
    except Exception as e:
        logger.error(f"Tool '{tool_name}' raised an error: {e}", exc_info=True)
        return {"error": str(e)}
