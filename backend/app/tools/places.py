"""Overpass (OpenStreetMap) places search — restaurants and attractions.

No key required; fair-use limits apply, so callers should cache results.
Venue IDs are stable OSM refs (e.g. "osm:node/123456") — they double as
the offer_id a restaurant reservation routes through the mock provider.
"""

import logging

import httpx
from pydantic import BaseModel, Field

from backend.app.config import settings
from backend.app.tools.base import BaseTool
from backend.app.tools.geo import USER_AGENT, geocode

logger = logging.getLogger(__name__)

_MAX_PLACES = 10
_SEARCH_RADIUS_M = 3000

# category → Overpass tag filter
_CATEGORY_FILTERS = {
    "restaurant": '["amenity"="restaurant"]',
    "attraction": '["tourism"="attraction"]',
}


class PlacesInput(BaseModel):
    location: str                     # city name, geocoded via Nominatim
    category: str = "restaurant"      # "restaurant" | "attraction"
    cuisine: str = ""                 # optional cuisine filter (restaurants)


class Place(BaseModel):
    venue_id: str                     # "osm:node/123456" — bookable handle
    name: str
    category: str
    cuisine: str = ""
    latitude: float
    longitude: float
    tags: dict = Field(default_factory=dict)


class PlacesResult(BaseModel):
    places: list[Place] = Field(default_factory=list)


class PlacesTool(BaseTool[PlacesInput, PlacesResult]):
    latency_budget_s: float = 15.0

    def _run(self, input: PlacesInput) -> PlacesResult:  # noqa: A002
        tag_filter = _CATEGORY_FILTERS.get(input.category)
        if tag_filter is None:
            raise ValueError(f"Unknown place category {input.category!r}")

        lat, lon = geocode(input.location)

        cuisine_filter = ""
        if input.cuisine:
            cuisine_filter = f'["cuisine"~"{input.cuisine}",i]'
        query = (
            f"[out:json][timeout:10];"
            f'node{tag_filter}{cuisine_filter}["name"]'
            f"(around:{_SEARCH_RADIUS_M},{lat},{lon});"
            f"out body {_MAX_PLACES};"
        )

        with httpx.Client(timeout=self.latency_budget_s) as client:
            resp = client.post(
                settings.OVERPASS_BASE_URL,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},  # Overpass 406s without a UA
            )
            resp.raise_for_status()

        elements = resp.json().get("elements", [])
        places = [
            Place(
                venue_id=f"osm:node/{el['id']}",
                name=el.get("tags", {}).get("name", "Unnamed"),
                category=input.category,
                cuisine=el.get("tags", {}).get("cuisine", ""),
                latitude=el.get("lat", 0.0),
                longitude=el.get("lon", 0.0),
                tags=el.get("tags", {}),
            )
            for el in elements
        ]
        logger.info(
            "PlacesTool: %d %s(s) for %s%s",
            len(places),
            input.category,
            input.location,
            f" (cuisine={input.cuisine})" if input.cuisine else "",
        )
        return PlacesResult(places=places)
