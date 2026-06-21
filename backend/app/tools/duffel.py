"""Duffel flight and stays search tools.

Flights: Uses the duffel-api SDK in sandbox mode where "Duffel Airways"
reliably returns non-empty offers for any route.

Stays: Uses Duffel's Stays REST API via httpx (SDK 0.6.2 doesn't expose
stays). Nominatim geocodes the destination city to coordinates first.

On any upstream failure, BaseTool.run() returns a degraded ToolResult so
the orchestrator handles unavailability gracefully.
"""

import logging
import re
import time

import httpx
from pydantic import BaseModel

from backend.app.config import settings
from backend.app.tools.base import BaseTool

logger = logging.getLogger(__name__)

_MAX_OFFERS = 10


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
        if not settings.DUFFEL_API_KEY:
            raise ValueError("DUFFEL_API_KEY is not set")

        from duffel_api import Duffel  # import inside _run to keep it swappable

        client = Duffel(access_token=settings.DUFFEL_API_KEY)

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

        passengers = [{"type": "adult"} for _ in range(input.passengers)]

        offer_request = (
            client.offer_requests.create()
            .slices(slices)
            .passengers(passengers)
            .cabin_class(input.cabin_class)
            .return_offers()
            .execute()
        )

        raw_offers = list(offer_request.offers)[:_MAX_OFFERS]

        offers = []
        for raw in raw_offers:
            outbound = raw.slices[0]
            first_segment = outbound.segments[0]
            stops = len(outbound.segments) - 1
            carrier = getattr(raw.owner, "name", "Unknown")
            dep_at = getattr(first_segment, "departing_at", "")
            last_segment = outbound.segments[-1]
            arr_at = getattr(last_segment, "arriving_at", "")
            duration = _iso8601_duration_to_minutes(getattr(outbound, "duration", "") or "")

            offers.append(
                FlightOffer(
                    offer_id=raw.id,
                    price=float(raw.total_amount),
                    currency=raw.total_currency,
                    carrier=carrier,
                    departure_at=dep_at,
                    arrival_at=arr_at,
                    duration_minutes=duration,
                    stops=stops,
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

_DUFFEL_BASE_URL = "https://api.duffel.com"
_NOMINATIM_UA = "WanderWise/0.1 (portfolio-project; amruthajayachandra.dhara@gmail.com)"
_MAX_STAYS = 10


class DuffelStaysInput(BaseModel):
    destination: str   # city name — geocoded to coordinates for the Duffel request
    check_in: str      # YYYY-MM-DD
    check_out: str     # YYYY-MM-DD
    guests: int = 1


class HotelOffer(BaseModel):
    property_id: str
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
        if not settings.DUFFEL_API_KEY:
            raise ValueError("DUFFEL_API_KEY is not set")

        lat, lon = self._geocode(input.destination)

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

        headers = {
            "Authorization": f"Bearer {settings.DUFFEL_API_KEY}",
            "Duffel-Version": "v2",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        with httpx.Client(timeout=self.latency_budget_s) as client:
            resp = client.post(
                f"{_DUFFEL_BASE_URL}/stays/search",
                json=payload,
                headers=headers,
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

    def _geocode(self, city: str) -> tuple[float, float]:
        time.sleep(1)  # Nominatim 1 req/sec policy
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": city, "format": "json", "limit": 1},
                headers={"User-Agent": _NOMINATIM_UA},
            )
            resp.raise_for_status()
        results = resp.json()
        if not results:
            raise ValueError(f"Location not found: {city!r}")
        return float(results[0]["lat"]), float(results[0]["lon"])

    @staticmethod
    def _night_count(check_in: str, check_out: str) -> int:
        from datetime import date
        try:
            return max((date.fromisoformat(check_out) - date.fromisoformat(check_in)).days, 1)
        except ValueError:
            return 1
