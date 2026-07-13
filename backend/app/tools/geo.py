"""Shared Nominatim geocoding — used by the stays and places tools.

Respects the 1 req/sec fair-use policy with a descriptive User-Agent.
Raises on unknown locations; callers run inside degrade-safe tool wrappers.
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

# Descriptive UA required by OSM services (Nominatim policy; Overpass 406s without one)
USER_AGENT = "WanderWise/0.1 (portfolio-project; amruthajayachandra.dhara@gmail.com)"


def geocode(city: str) -> tuple[float, float]:
    time.sleep(1)  # Nominatim 1 req/sec policy
    with httpx.Client(timeout=10) as client:
        resp = client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": city, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
    results = resp.json()
    if not results:
        raise ValueError(f"Location not found: {city!r}")
    return float(results[0]["lat"]), float(results[0]["lon"])
