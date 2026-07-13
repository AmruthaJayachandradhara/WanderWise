"""Duffel booking backend — real sandbox flight orders + Stays hotel bookings.

All calls go straight to Duffel's REST API (v2) via httpx — the duffel-api
SDK was dropped (v1-shaped models the API no longer accepts). Flight orders
confirm instantly on create, so confirm() is a documented pass-through
returning the booking reference. Hotels follow the Stays flow:
search result → fetch rates → quote → booking.

Booked against the "Duffel Airways" test airline in sandbox mode; no real
money moves. All methods return ToolResult and never raise.
"""

import logging
import time

import httpx

from backend.app.booking.provider import (
    AvailabilityCheck,
    BookingOffer,
    BookingSearchRequest,
    BookingSearchResult,
    Cancellation,
    Confirmation,
    Reservation,
    ReservationRequest,
)
from backend.app.config import settings
from backend.app.tools.base import ToolResult
from backend.app.tools.duffel import _DUFFEL_BASE_URL, duffel_headers

logger = logging.getLogger(__name__)

_TIMEOUT_S = 20.0


def _guard(fn):
    """Wrap a provider method: time it, never raise, degrade on exception."""

    def wrapper(self, *args, **kwargs):
        start = time.monotonic()
        try:
            result = fn(self, *args, **kwargs)
            result.latency_ms = (time.monotonic() - start) * 1000
            return result
        except Exception as exc:
            logger.warning("%s.%s failed: %s", type(self).__name__, fn.__name__, exc)
            return ToolResult(
                success=False,
                degraded=True,
                error=str(exc),
                latency_ms=(time.monotonic() - start) * 1000,
            )

    return wrapper


class DuffelBookingProvider:
    provider_name = "duffel"
    booking_types = ("flight", "hotel")

    def _request(
        self,
        method: str,
        path: str,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        """Single REST seam — monkeypatched in offline tests."""
        with httpx.Client(timeout=_TIMEOUT_S) as client:
            resp = client.request(
                method,
                f"{_DUFFEL_BASE_URL}{path}",
                json=json,
                params=params,
                headers=duffel_headers(),
            )
            resp.raise_for_status()
        return resp.json().get("data", {})

    @staticmethod
    def _is_flight(entity_id: str) -> bool:
        # Duffel flight offers/orders are prefixed off_/ord_; stays ids are not.
        return entity_id.startswith(("off_", "ord_"))

    # --- BookingProvider lifecycle ---

    @_guard
    def search(self, req: BookingSearchRequest) -> ToolResult[BookingSearchResult]:
        """Delegate to the Phase 2 search tools, mapped onto the contract."""
        if req.booking_type == "flight":
            from backend.app.tools.duffel import DuffelFlightInput, DuffelFlightTool

            result = DuffelFlightTool().run(DuffelFlightInput(**req.params))
            if not result.success:
                return ToolResult(success=False, degraded=result.degraded, error=result.error)
            offers = [
                BookingOffer(
                    offer_id=o.offer_id,
                    booking_type="flight",
                    description=f"{o.carrier} {o.departure_at} → {o.arrival_at}",
                    price=o.price,
                    currency=o.currency,
                    metadata=o.model_dump(),
                )
                for o in result.data.offers
            ]
        elif req.booking_type == "hotel":
            from backend.app.tools.duffel import DuffelStaysInput, DuffelStaysTool

            result = DuffelStaysTool().run(DuffelStaysInput(**req.params))
            if not result.success:
                return ToolResult(success=False, degraded=result.degraded, error=result.error)
            offers = [
                BookingOffer(
                    offer_id=o.result_id or o.property_id,
                    booking_type="hotel",
                    description=o.name,
                    price=o.total_price,
                    currency=o.currency,
                    metadata=o.model_dump(),
                )
                for o in result.data.offers
            ]
        else:
            return ToolResult(success=False, error=f"Unsupported booking type {req.booking_type!r}")
        return ToolResult(success=True, data=BookingSearchResult(offers=offers))

    @_guard
    def check(self, offer_id: str) -> ToolResult[AvailabilityCheck]:
        if self._is_flight(offer_id):
            try:
                offer = self._request("GET", f"/air/offers/{offer_id}")
                return ToolResult(
                    success=True,
                    data=AvailabilityCheck(
                        offer_id=offer_id,
                        available=True,
                        price=float(offer["total_amount"]),
                        currency=offer["total_currency"],
                    ),
                )
            except httpx.HTTPStatusError as exc:  # expired offers 404/422
                return ToolResult(
                    success=True,
                    data=AvailabilityCheck(
                        offer_id=offer_id, available=False, detail=str(exc)
                    ),
                )
        return ToolResult(
            success=True,
            data=AvailabilityCheck(
                offer_id=offer_id,
                available=True,
                detail="Stays availability validated at quote time",
            ),
        )

    @_guard
    def reserve(self, req: ReservationRequest) -> ToolResult[Reservation]:
        if req.booking_type == "flight":
            return self._reserve_flight(req)
        if req.booking_type == "hotel":
            return self._reserve_hotel(req)
        return ToolResult(success=False, error=f"Unsupported booking type {req.booking_type!r}")

    def _reserve_flight(self, req: ReservationRequest) -> ToolResult[Reservation]:
        offer = self._request("GET", f"/air/offers/{req.offer_id}")

        pax_details = {**settings.BOOKING_PASSENGER, **req.details.get("passenger", {})}
        passengers = [{"id": p["id"], **pax_details} for p in offer["passengers"]]
        order = self._request(
            "POST",
            "/air/orders",
            json={
                "data": {
                    "type": "instant",
                    "selected_offers": [req.offer_id],
                    "passengers": passengers,
                    "payments": [
                        {
                            "type": "balance",
                            "currency": offer["total_currency"],
                            "amount": offer["total_amount"],
                        }
                    ],
                }
            },
        )
        logger.info(
            "Duffel order created: %s (reference %s)",
            order.get("id"),
            order.get("booking_reference"),
        )
        return ToolResult(
            success=True,
            data=Reservation(
                reservation_id=order.get("id", ""),
                offer_id=req.offer_id,
                booking_type="flight",
                status="confirmed",  # Duffel instant orders confirm on create
                provider=self.provider_name,
                details={
                    "booking_reference": order.get("booking_reference", ""),
                    "amount": order.get("total_amount", ""),
                    "currency": order.get("total_currency", ""),
                },
            ),
        )

    def _reserve_hotel(self, req: ReservationRequest) -> ToolResult[Reservation]:
        # Stays flow: search result → rates → quote → booking.
        rates = self._request(
            "POST", f"/stays/search_results/{req.offer_id}/actions/fetch_all_rates"
        )
        rooms = rates.get("accommodation", {}).get("rooms", [])
        all_rates = [r for room in rooms for r in room.get("rates", [])]
        if not all_rates:
            return ToolResult(success=False, error="No bookable rates for this stay")
        cheapest = min(all_rates, key=lambda r: float(r.get("total_amount", "inf")))

        quote = self._request(
            "POST", "/stays/quotes", json={"data": {"rate_id": cheapest["id"]}}
        )

        guest = {**settings.BOOKING_PASSENGER, **req.details.get("guest", {})}
        booking = self._request(
            "POST",
            "/stays/bookings",
            json={
                "data": {
                    "quote_id": quote["id"],
                    "guests": [
                        {
                            "given_name": guest["given_name"],
                            "family_name": guest["family_name"],
                        }
                    ],
                    "email": guest["email"],
                    "phone_number": guest["phone_number"],
                }
            },
        )
        logger.info(
            "Duffel Stays booking created: %s (reference %s)",
            booking.get("id"),
            booking.get("reference"),
        )
        return ToolResult(
            success=True,
            data=Reservation(
                reservation_id=booking.get("id", ""),
                offer_id=req.offer_id,
                booking_type="hotel",
                status="confirmed",
                provider=self.provider_name,
                details={
                    "booking_reference": booking.get("reference", ""),
                    "check_in": booking.get("check_in_date", ""),
                    "check_out": booking.get("check_out_date", ""),
                },
            ),
        )

    @_guard
    def confirm(self, reservation_id: str) -> ToolResult[Confirmation]:
        """Pass-through: Duffel orders/bookings confirm at creation.

        Re-fetches the record and returns its booking reference as the
        confirmation ID, so confirm() is uniform across providers.
        """
        if self._is_flight(reservation_id):
            order = self._request("GET", f"/air/orders/{reservation_id}")
            confirmation_id = order.get("booking_reference", "")
        else:
            booking = self._request("GET", f"/stays/bookings/{reservation_id}")
            confirmation_id = booking.get("reference", "")
        return ToolResult(
            success=True,
            data=Confirmation(
                confirmation_id=confirmation_id,
                reservation_id=reservation_id,
                status="confirmed",
                provider=self.provider_name,
            ),
        )

    @_guard
    def cancel(self, reservation_id: str) -> ToolResult[Cancellation]:
        if self._is_flight(reservation_id):
            cancellation = self._request(
                "POST",
                "/air/order_cancellations",
                json={"data": {"order_id": reservation_id}},
            )
            self._request(
                "POST",
                f"/air/order_cancellations/{cancellation['id']}/actions/confirm",
            )
        else:
            self._request(
                "POST", f"/stays/bookings/{reservation_id}/actions/cancel"
            )
        logger.info("Duffel booking cancelled: %s", reservation_id)
        return ToolResult(
            success=True,
            data=Cancellation(
                reservation_id=reservation_id,
                status="cancelled",
                provider=self.provider_name,
            ),
        )


def get_provider() -> DuffelBookingProvider:
    return DuffelBookingProvider()
