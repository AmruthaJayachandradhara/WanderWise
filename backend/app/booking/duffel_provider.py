"""Duffel booking backend — real sandbox flight + Stays hotel booking.

Stub in Phase 4 Step 1; the full order-create/confirm/cancel flow lands in
Step 3. Search continues to live in tools/duffel.py (Phase 2); this provider
covers the booking lifecycle behind the BookingProvider contract.
"""

import logging

from backend.app.booking.provider import (
    AvailabilityCheck,
    BookingSearchRequest,
    BookingSearchResult,
    Cancellation,
    Confirmation,
    Reservation,
    ReservationRequest,
)
from backend.app.tools.base import ToolResult

logger = logging.getLogger(__name__)

_NOT_IMPLEMENTED = "Duffel booking not implemented yet (Phase 4 Step 3)"


class DuffelBookingProvider:
    provider_name = "duffel"
    booking_types = ("flight", "hotel")

    def search(self, req: BookingSearchRequest) -> ToolResult[BookingSearchResult]:
        return ToolResult(success=False, degraded=True, error=_NOT_IMPLEMENTED)

    def check(self, offer_id: str) -> ToolResult[AvailabilityCheck]:
        return ToolResult(success=False, degraded=True, error=_NOT_IMPLEMENTED)

    def reserve(self, req: ReservationRequest) -> ToolResult[Reservation]:
        return ToolResult(success=False, degraded=True, error=_NOT_IMPLEMENTED)

    def confirm(self, reservation_id: str) -> ToolResult[Confirmation]:
        return ToolResult(success=False, degraded=True, error=_NOT_IMPLEMENTED)

    def cancel(self, reservation_id: str) -> ToolResult[Cancellation]:
        return ToolResult(success=False, degraded=True, error=_NOT_IMPLEMENTED)


def get_provider() -> DuffelBookingProvider:
    return DuffelBookingProvider()
