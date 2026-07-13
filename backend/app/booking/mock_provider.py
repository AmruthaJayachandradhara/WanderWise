"""Mock booking backend — real HTTP against the self-hosted reservation service.

Transport is config-driven:
  - RESERVATION_SERVICE_URL set → plain network client (docker-compose /
    standalone deployment).
  - unset (default) → httpx ASGITransport straight into the FastAPI app:
    full HTTP semantics (routing, status codes, Idempotency-Key header)
    with no network hop — correct for the single-container HF Space.

Same BookingProvider contract as Duffel: a restaurant reservation and a
flight booking are interchangeable behind one seam.
"""

import asyncio
import logging
import time

import httpx

from backend.app.booking.provider import (
    AvailabilityCheck,
    BookingSearchRequest,
    BookingSearchResult,
    Cancellation,
    Confirmation,
    Reservation,
    ReservationRequest,
)
from backend.app.config import settings
from backend.app.tools.base import ToolResult

logger = logging.getLogger(__name__)

_TIMEOUT_S = 10.0


class MockBookingProvider:
    provider_name = "mock"
    booking_types = ("restaurant",)

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        base_url = settings.RESERVATION_SERVICE_URL
        if base_url:
            with httpx.Client(base_url=base_url, timeout=_TIMEOUT_S) as client:
                return client.request(method, path, **kwargs)

        # In-process: route through the ASGI app directly. Import here so the
        # provider module stays importable without FastAPI app side effects.
        from backend.app.reservation_service.service import app as reservation_app

        async def _call() -> httpx.Response:
            transport = httpx.ASGITransport(app=reservation_app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://reservation", timeout=_TIMEOUT_S
            ) as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(_call())

    def search(self, req: BookingSearchRequest) -> ToolResult[BookingSearchResult]:
        return ToolResult(
            success=False,
            error="Mock provider does not search; restaurant discovery uses the places tool",
        )

    def check(self, offer_id: str) -> ToolResult[AvailabilityCheck]:
        # Availability is slot-scoped; conflicts are enforced at reserve (409).
        return ToolResult(
            success=True,
            data=AvailabilityCheck(
                offer_id=offer_id,
                available=True,
                detail="Availability enforced at reserve time (409 on slot conflict)",
            ),
        )

    def reserve(self, req: ReservationRequest) -> ToolResult[Reservation]:
        start = time.monotonic()
        try:
            resp = self._request(
                "POST",
                "/reservations",
                json={
                    "venue_id": req.offer_id,
                    "venue_name": req.details.get("venue_name", ""),
                    "slot": req.details.get("slot", ""),
                    "party_size": req.details.get("party_size", 2),
                },
                headers={"Idempotency-Key": req.idempotency_key},
            )
            latency_ms = (time.monotonic() - start) * 1000
            if resp.status_code == 409:
                return ToolResult(
                    success=False,
                    error=resp.json().get("detail", "slot conflict"),
                    latency_ms=latency_ms,
                )
            resp.raise_for_status()
            body = resp.json()
            return ToolResult(
                success=True,
                data=Reservation(
                    reservation_id=body["reservation_id"],
                    offer_id=req.offer_id,
                    booking_type=req.booking_type,
                    status=body["status"],
                    provider=self.provider_name,
                    details=body,
                ),
                latency_ms=latency_ms,
            )
        except Exception as exc:
            logger.warning("Mock reserve failed: %s", exc)
            return ToolResult(
                success=False,
                degraded=True,
                error=str(exc),
                latency_ms=(time.monotonic() - start) * 1000,
            )

    def confirm(self, reservation_id: str) -> ToolResult[Confirmation]:
        start = time.monotonic()
        try:
            resp = self._request("POST", f"/reservations/{reservation_id}/confirm")
            latency_ms = (time.monotonic() - start) * 1000
            if resp.status_code in (404, 409):
                return ToolResult(
                    success=False,
                    error=resp.json().get("detail", f"HTTP {resp.status_code}"),
                    latency_ms=latency_ms,
                )
            resp.raise_for_status()
            body = resp.json()
            return ToolResult(
                success=True,
                data=Confirmation(
                    confirmation_id=body["confirmation_id"],
                    reservation_id=reservation_id,
                    status=body["status"],
                    provider=self.provider_name,
                ),
                latency_ms=latency_ms,
            )
        except Exception as exc:
            logger.warning("Mock confirm failed: %s", exc)
            return ToolResult(
                success=False,
                degraded=True,
                error=str(exc),
                latency_ms=(time.monotonic() - start) * 1000,
            )

    def cancel(self, reservation_id: str) -> ToolResult[Cancellation]:
        start = time.monotonic()
        try:
            resp = self._request("DELETE", f"/reservations/{reservation_id}")
            latency_ms = (time.monotonic() - start) * 1000
            if resp.status_code == 404:
                return ToolResult(
                    success=False,
                    error=resp.json().get("detail", "not found"),
                    latency_ms=latency_ms,
                )
            resp.raise_for_status()
            body = resp.json()
            return ToolResult(
                success=True,
                data=Cancellation(
                    reservation_id=reservation_id,
                    status=body["status"],
                    provider=self.provider_name,
                ),
                latency_ms=latency_ms,
            )
        except Exception as exc:
            logger.warning("Mock cancel failed: %s", exc)
            return ToolResult(
                success=False,
                degraded=True,
                error=str(exc),
                latency_ms=(time.monotonic() - start) * 1000,
            )


def get_provider() -> MockBookingProvider:
    return MockBookingProvider()
