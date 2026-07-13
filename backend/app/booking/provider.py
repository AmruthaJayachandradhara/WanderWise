"""BookingProvider — the single seam every booking goes through.

One interface unifies real and mock booking: flights and hotels route to
Duffel, restaurants route to the self-hosted reservation service. Which
backend serves which booking type is config (BOOKING_PROVIDER_MAP), not
code — swapping in OpenTable later is a config change, not a rewrite.

Lifecycle: search → check → reserve → confirm → cancel.
Every method returns a ToolResult (Phase 1 tool contract) and never raises;
only get_provider() raises, on a misconfigured booking type.
"""

import importlib
import logging
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from backend.app.config import settings
from backend.app.tools.base import ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed I/O shared by every provider
# ---------------------------------------------------------------------------

class BookingOffer(BaseModel):
    """One bookable option returned by search()."""

    offer_id: str
    booking_type: str                    # "flight" | "hotel" | "restaurant"
    description: str = ""
    price: float | None = None
    currency: str | None = None
    metadata: dict = Field(default_factory=dict)


class BookingSearchRequest(BaseModel):
    booking_type: str
    params: dict = Field(default_factory=dict)  # provider-specific search args


class BookingSearchResult(BaseModel):
    offers: list[BookingOffer] = Field(default_factory=list)


class AvailabilityCheck(BaseModel):
    """Result of re-validating an offer just before reserving."""

    offer_id: str
    available: bool
    price: float | None = None
    currency: str | None = None
    detail: str = ""


class ReservationRequest(BaseModel):
    booking_type: str
    offer_id: str
    idempotency_key: str                 # retried reserve must not double-book
    details: dict = Field(default_factory=dict)  # passengers / guests / party


class Reservation(BaseModel):
    reservation_id: str
    offer_id: str
    booking_type: str
    status: str                          # "reserved" | "confirmed" | "cancelled"
    provider: str
    details: dict = Field(default_factory=dict)


class Confirmation(BaseModel):
    confirmation_id: str
    reservation_id: str
    status: str
    provider: str


class Cancellation(BaseModel):
    reservation_id: str
    status: str                          # "cancelled"
    provider: str


# ---------------------------------------------------------------------------
# The provider contract
# ---------------------------------------------------------------------------

@runtime_checkable
class BookingProvider(Protocol):
    """Every booking backend implements this five-step lifecycle."""

    provider_name: str
    booking_types: tuple[str, ...]

    def search(self, req: BookingSearchRequest) -> ToolResult[BookingSearchResult]: ...

    def check(self, offer_id: str) -> ToolResult[AvailabilityCheck]: ...

    def reserve(self, req: ReservationRequest) -> ToolResult[Reservation]: ...

    def confirm(self, reservation_id: str) -> ToolResult[Confirmation]: ...

    def cancel(self, reservation_id: str) -> ToolResult[Cancellation]: ...


# ---------------------------------------------------------------------------
# Config-driven factory
# ---------------------------------------------------------------------------

# provider name → module exposing get_provider() -> BookingProvider
_PROVIDER_MODULES = {
    "duffel": "backend.app.booking.duffel_provider",
    "mock": "backend.app.booking.mock_provider",
}

_instances: dict[str, BookingProvider] = {}


def get_provider(booking_type: str) -> BookingProvider:
    """Resolve a booking type to its configured backend (lazy singleton)."""
    provider_name = settings.BOOKING_PROVIDER_MAP.get(booking_type)
    if provider_name is None:
        raise ValueError(
            f"No booking provider configured for booking type {booking_type!r} "
            f"(known types: {sorted(settings.BOOKING_PROVIDER_MAP)})"
        )
    module_path = _PROVIDER_MODULES.get(provider_name)
    if module_path is None:
        raise ValueError(
            f"Unknown booking provider {provider_name!r} for type {booking_type!r} "
            f"(known providers: {sorted(_PROVIDER_MODULES)})"
        )
    if provider_name not in _instances:
        module = importlib.import_module(module_path)
        _instances[provider_name] = module.get_provider()
        logger.info("Booking provider %r initialised for type %r", provider_name, booking_type)
    return _instances[provider_name]
