"""Duffel flight and stays search tools.

Both use Duffel's REST API (v2) directly via httpx. The duffel-api SDK was
dropped in Phase 4: its models are v1-shaped and the API no longer accepts
v1 requests, so raw httpx is the honest integration for flights and stays
alike. Stays destinations are geocoded to coordinates via Nominatim first.

On any upstream failure, BaseTool.run() returns a degraded ToolResult so
the orchestrator handles unavailability gracefully.
"""

import logging
import re

import httpx
from pydantic import BaseModel

from backend.app.config import settings
from backend.app.tools.base import BaseTool
from backend.app.tools.geo import geocode

logger = logging.getLogger(__name__)

_MAX_OFFERS = 10
_DUFFEL_BASE_URL = "https://api.duffel.com"


def duffel_headers() -> dict:
    """Auth + version headers for every Duffel REST call (also used by booking/)."""
    if not settings.DUFFEL_API_KEY:
        raise ValueError("DUFFEL_API_KEY is not set")
    return {
        "Authorization": f"Bearer {settings.DUFFEL_API_KEY}",
        "Duffel-Version": "v2",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# --- Schemas ---

class DuffelFlightInput(BaseModel):
    origin: str              # IATA code, e.g. "SFO"
    destination: str         # IATA code, e.g. "TYO"
    departure_date: str      # YYYY-MM-DD
    return_date: str | None = None
    passengers: int = 1
    cabin_class: str = "economy"


class FlightOffer(BaseModel):
    offer_id: str
    price: float
    currency: str
    carrier: str
    departure_at: str
    arrival_at: str
    duration_minutes: int
    stops: int


class DuffelFlightOffers(BaseModel):
    offers: list[FlightOffer]


# --- Helpers ---

def _iso8601_duration_to_minutes(duration: str) -> int:
    """Convert ISO 8601 duration string like 'PT11H30M' to total minutes."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration or "")
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return hours * 60 + minutes


# --- Implementation ---

class DuffelFlightTool(BaseTool[DuffelFlightInput, DuffelFlightOffers]):
    latency_budget_s: float = 15.0

    def _run(self, input: DuffelFlightInput) -> DuffelFlightOffers:  # noqa: A002
        slices = [
            {
                "origin": input.origin,
                "destination": input.destination,
                "departure_date": input.departure_date,
            }
        ]
        if input.return_date:
            slices.append(
                {
                    "origin": input.destination,
                    "destination": input.origin,
                    "departure_date": input.return_date,
                }
            )

        payload = {
            "data": {
                "slices": slices,
                "passengers": [{"type": "adult"} for _ in range(input.passengers)],
                "cabin_class": input.cabin_class,
            }
        }

        with httpx.Client(timeout=self.latency_budget_s) as client:
            resp = client.post(
                f"{_DUFFEL_BASE_URL}/air/offer_requests",
                params={"return_offers": "true"},
                json=payload,
                headers=duffel_headers(),
            )
            resp.raise_for_status()

        raw_offers = resp.json().get("data", {}).get("offers", [])[:_MAX_OFFERS]

        offers = []
        for raw in raw_offers:
            outbound = raw["slices"][0]
            segments = outbound.get("segments", [])
            offers.append(
                FlightOffer(
                    offer_id=raw["id"],
                    price=float(raw["total_amount"]),
                    currency=raw["total_currency"],
                    carrier=raw.get("owner", {}).get("name", "Unknown"),
                    departure_at=segments[0].get("departing_at", "") if segments else "",
                    arrival_at=segments[-1].get("arriving_at", "") if segments else "",
                    duration_minutes=_iso8601_duration_to_minutes(outbound.get("duration") or ""),
                    stops=max(len(segments) - 1, 0),
                )
            )

        logger.info(
            "DuffelFlightTool: %d offers for %s→%s on %s",
            len(offers),
            input.origin,
            input.destination,
            input.departure_date,
        )
        return DuffelFlightOffers(offers=offers)


# ---------------------------------------------------------------------------
# Stays tool
# ---------------------------------------------------------------------------

_MAX_STAYS = 10


class DuffelStaysInput(BaseModel):
    destination: str   # city name — geocoded to coordinates for the Duffel request
    check_in: str      # YYYY-MM-DD
    check_out: str     # YYYY-MM-DD
    guests: int = 1


class HotelOffer(BaseModel):
    property_id: str
    result_id: str = ""  # Duffel search-result id — required to book (Phase 4)
    name: str
    price_per_night: float
    currency: str
    total_price: float
    rating: float | None
    amenities: list[str]


class DuffelStaysOffers(BaseModel):
    offers: list[HotelOffer]


class DuffelStaysTool(BaseTool[DuffelStaysInput, DuffelStaysOffers]):
    latency_budget_s: float = 15.0

    def _run(self, input: DuffelStaysInput) -> DuffelStaysOffers:  # noqa: A002
        lat, lon = geocode(input.destination)

        payload = {
            "data": {
                "rooms": 1,
                "guests": [{"type": "adult"} for _ in range(input.guests)],
                "check_in_date": input.check_in,
                "check_out_date": input.check_out,
                "location": {
                    "geographic_coordinates": {
                        "latitude": lat,
                        "longitude": lon,
                        "radius": 10000,
                    }
                },
            }
        }

        with httpx.Client(timeout=self.latency_budget_s) as client:
            resp = client.post(
                f"{_DUFFEL_BASE_URL}/stays/search",
                json=payload,
                headers=duffel_headers(),
            )
            resp.raise_for_status()

        data = resp.json().get("data", {})
        results = data.get("results", [])[:_MAX_STAYS]

        nights = self._night_count(input.check_in, input.check_out)

        offers = []
        for r in results:
            acc = r.get("accommodation", {})
            price_per_night = float(r.get("cheapest_rate_total_amount", 0)) / max(nights, 1)
            currency = r.get("cheapest_rate_currency", "USD")
            total = float(r.get("cheapest_rate_total_amount", 0))
            rating_raw = acc.get("rating", {})
            rating = float(rating_raw.get("value", 0)) if rating_raw else None
            amenities = [a.get("type", "") for a in acc.get("amenities", [])]
            offers.append(
                HotelOffer(
                    property_id=acc.get("id", r.get("id", "")),
                    result_id=r.get("id", ""),
                    name=acc.get("name", "Unknown property"),
                    price_per_night=round(price_per_night, 2),
                    currency=currency,
                    total_price=round(total, 2),
                    rating=rating,
                    amenities=amenities,
                )
            )

        logger.info(
            "DuffelStaysTool: %d offers for %s (%s→%s)",
            len(offers), input.destination, input.check_in, input.check_out,
        )
        return DuffelStaysOffers(offers=offers)

    @staticmethod
    def _night_count(check_in: str, check_out: str) -> int:
        from datetime import date
        try:
            return max((date.fromisoformat(check_out) - date.fromisoformat(check_in)).days, 1)
        except ValueError:
            return 1
