"""Mock booking backend — routes to the self-hosted reservation service.

Stub in Phase 4 Step 1; the HTTP client against the reservation service
(in-process ASGI transport by default, RESERVATION_SERVICE_URL when set)
lands in Step 2.
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

_NOT_IMPLEMENTED = "Mock reservation service not implemented yet (Phase 4 Step 2)"


class MockBookingProvider:
    provider_name = "mock"
    booking_types = ("restaurant",)

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


def get_provider() -> MockBookingProvider:
    return MockBookingProvider()
