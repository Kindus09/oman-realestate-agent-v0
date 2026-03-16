# agent/models.py
#
# Pydantic data models for the agent layer.
# These models describe the shape of data flowing through the agent:
#   - Property: one cleaned listing from the JSON data file.
#   - SearchFilters: what the user is looking for.
#   - SearchResult: what we return to Claude after a tool call.
#
# Why Pydantic?
#   Pydantic validates data at runtime (catches type mismatches) and gives us
#   free .model_dump() / .model_json_schema() methods. The JSON schema method
#   is particularly useful for generating Claude tool definitions automatically.

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, field_validator


class Property(BaseModel):
    """
    Represents one property listing as stored in clean_listings.json.
    All fields are optional because different sites provide different data.
    """
    title:         Optional[str]   = None
    price_raw:     Optional[str]   = None   # original price string, e.g. "OMR 450 / month"
    price_omr:     Optional[float] = None   # numeric OMR value extracted by data_cleaner
    frequency:     Optional[str]   = None   # "month", "year", None (for sale)
    location:      Optional[str]   = None   # normalised area name
    bedrooms:      Optional[int]   = None
    bathrooms:     Optional[int]   = None
    size_sqft:     Optional[int]   = None
    property_type: Optional[str]   = None
    listing_type:  Optional[str]   = None   # "sale" or "rent"
    description:   Optional[str]   = None
    listing_url:   Optional[str]   = None
    source:        Optional[str]   = None   # which site this came from
    date_scraped:  Optional[str]   = None

    @field_validator("listing_type")
    @classmethod
    def normalise_listing_type(cls, v):
        """Accept 'sale'/'rent' but also handle 'for sale'/'for rent'."""
        if v is None:
            return v
        v = v.lower().strip()
        if "rent" in v:
            return "rent"
        if "sale" in v or "buy" in v:
            return "sale"
        return v

    def summary(self) -> str:
        """One-line human-readable summary for display in agent responses."""
        parts = []
        if self.title:
            parts.append(self.title)
        if self.price_raw:
            parts.append(f"@ {self.price_raw}")
        if self.location:
            parts.append(f"in {self.location}")
        if self.bedrooms is not None:
            parts.append(f"{self.bedrooms}BR")
        if self.size_sqft:
            parts.append(f"{self.size_sqft:,} sqft")
        if self.listing_url:
            parts.append(f"→ {self.listing_url}")
        return " | ".join(parts) if parts else "(no details)"


class SearchFilters(BaseModel):
    """
    Parameters the user can pass to the search_listings tool.
    All filters are optional — omit any you don't want to filter on.
    """
    listing_type:     Optional[str]   = None   # "sale" or "rent"
    location:         Optional[str]   = None   # area name, partial match OK
    min_price_omr:    Optional[float] = None
    max_price_omr:    Optional[float] = None
    min_bedrooms:     Optional[int]   = None
    max_bedrooms:     Optional[int]   = None
    property_type:    Optional[str]   = None   # "apartment", "villa", etc.
    source:           Optional[str]   = None   # filter by site name
    limit:            int             = 10     # max results to return


class SearchResult(BaseModel):
    """
    What the search_listings tool returns to Claude after a query.
    Wraps the list of matches with metadata about the query.
    """
    total_found:  int
    returned:     int
    filters_used: dict
    listings:     list[Property]

    def to_text(self) -> str:
        """
        Format the result as plain text that Claude can include in its reply.
        """
        lines = [
            f"Found {self.total_found} matching listings (showing {self.returned}):",
            "",
        ]
        for i, prop in enumerate(self.listings, start=1):
            lines.append(f"{i}. {prop.summary()}")

        return "\n".join(lines)


class AreaStats(BaseModel):
    """
    Statistics for a specific area returned by the get_area_stats tool.
    """
    area:             str
    listing_type:     str              # "sale", "rent", or "all"
    total_listings:   int
    avg_price_omr:    Optional[float]  = None
    min_price_omr:    Optional[float]  = None
    max_price_omr:    Optional[float]  = None
    avg_bedrooms:     Optional[float]  = None
    sources:          list[str]        = []    # which sites contributed listings
