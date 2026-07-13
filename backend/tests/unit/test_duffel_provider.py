"""Offline unit tests for the Duffel booking provider (Phase 4 Step 3).

The single REST seam (_request) is monkeypatched — no network, no live key.
Response shapes mirror the Duffel v2 API (verified against a sandbox run;
see data/fixtures/duffel_booking_sandbox.json).
"""

import pytest

from backend.app.booking.duffel_provider import DuffelBookingProvider
from backend.app.booking.provider import ReservationRequest

_OFFER = {
    "id": "off_123",
    "total_amount": "512.30",
    "total_currency": "USD",
    "passengers": [{"id": "pas_1"}],
}

_ORDER = {
    "id": "ord_123",
    "booking_reference": "RZPNX8",
    "total_amount": "512.30",
    "total_currency": "USD",
}


@pytest.fixture
def air_calls(monkeypatch):
    """Monkeypatch _request with a flight-flow fake; returns the call log."""
    calls = []

    def fake_request(self, method, path, json=None, params=None):
        calls.append({"method": method, "path": path, "json": json})
        if path == "/air/offers/off_123":
            return _OFFER
        if path == "/air/orders" and method == "POST":
            return _ORDER
        if path == "/air/orders/ord_123":
            return _ORDER
        if path == "/air/order_cancellations" and method == "POST":
            return {"id": "ocr_1", "order_id": json["data"]["order_id"]}
        if path == "/air/order_cancellations/ocr_1/actions/confirm":
            return {"id": "ocr_1", "confirmed_at": "2026-07-13T00:00:00Z"}
        raise AssertionError(f"unexpected {method} {path}")

    monkeypatch.setattr(DuffelBookingProvider, "_request", fake_request)
    return calls


def _flight_req():
    return ReservationRequest(
        booking_type="flight", offer_id="off_123", idempotency_key="k1"
    )


# ---------------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------------

def test_reserve_flight_creates_order(air_calls):
    result = DuffelBookingProvider().reserve(_flight_req())
    assert result.success
    assert result.data.reservation_id == "ord_123"
    assert result.data.status == "confirmed"
    assert result.data.details["booking_reference"] == "RZPNX8"

    order_call = next(c for c in air_calls if c["path"] == "/air/orders")
    body = order_call["json"]["data"]
    assert body["selected_offers"] == ["off_123"]
    assert body["passengers"][0]["id"] == "pas_1"
    assert body["passengers"][0]["given_name"]  # demo passenger merged in
    assert body["payments"] == [
        {"type": "balance", "currency": "USD", "amount": "512.30"}
    ]


def test_confirm_flight_returns_booking_reference(air_calls):
    result = DuffelBookingProvider().confirm("ord_123")
    assert result.success
    assert result.data.confirmation_id == "RZPNX8"


def test_cancel_flight_two_step(air_calls):
    result = DuffelBookingProvider().cancel("ord_123")
    assert result.success
    assert result.data.status == "cancelled"
    paths = [c["path"] for c in air_calls]
    assert paths == [
        "/air/order_cancellations",
        "/air/order_cancellations/ocr_1/actions/confirm",
    ]


def test_check_flight_available(air_calls):
    result = DuffelBookingProvider().check("off_123")
    assert result.success
    assert result.data.available
    assert result.data.price == 512.30


def test_reserve_without_key_degrades(monkeypatch):
    monkeypatch.setattr(
        "backend.app.tools.duffel.settings.DUFFEL_API_KEY", None
    )
    result = DuffelBookingProvider().reserve(_flight_req())
    assert not result.success
    assert result.degraded
    assert "DUFFEL_API_KEY" in result.error


# ---------------------------------------------------------------------------
# Hotels (Stays flow)
# ---------------------------------------------------------------------------

def test_reserve_hotel_rates_quote_booking(monkeypatch):
    calls = []

    def fake_request(self, method, path, json=None, params=None):
        calls.append(path)
        if "fetch_all_rates" in path:
            return {
                "accommodation": {
                    "rooms": [
                        {"rates": [
                            {"id": "rat_exp", "total_amount": "900.00"},
                            {"id": "rat_cheap", "total_amount": "450.00"},
                        ]}
                    ]
                }
            }
        if path == "/stays/quotes":
            assert json == {"data": {"rate_id": "rat_cheap"}}
            return {"id": "quo_1"}
        if path == "/stays/bookings":
            assert json["data"]["quote_id"] == "quo_1"
            return {
                "id": "bok_1",
                "reference": "HTL-7788",
                "check_in_date": "2026-08-01",
                "check_out_date": "2026-08-05",
            }
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(DuffelBookingProvider, "_request", fake_request)
    result = DuffelBookingProvider().reserve(
        ReservationRequest(booking_type="hotel", offer_id="res_abc", idempotency_key="k2")
    )
    assert result.success
    assert result.data.reservation_id == "bok_1"
    assert result.data.details["booking_reference"] == "HTL-7788"
    assert calls == [
        "/stays/search_results/res_abc/actions/fetch_all_rates",
        "/stays/quotes",
        "/stays/bookings",
    ]


def test_reserve_hotel_no_rates_fails_cleanly(monkeypatch):
    monkeypatch.setattr(
        DuffelBookingProvider,
        "_request",
        lambda self, method, path, json=None, params=None: {"accommodation": {"rooms": []}},
    )
    result = DuffelBookingProvider().reserve(
        ReservationRequest(booking_type="hotel", offer_id="res_abc", idempotency_key="k3")
    )
    assert not result.success
    assert not result.degraded
    assert "No bookable rates" in result.error


def test_cancel_hotel(monkeypatch):
    calls = []
    monkeypatch.setattr(
        DuffelBookingProvider,
        "_request",
        lambda self, method, path, json=None, params=None: calls.append(path) or {},
    )
    result = DuffelBookingProvider().cancel("bok_1")
    assert result.success
    assert calls == ["/stays/bookings/bok_1/actions/cancel"]


def test_unsupported_type_rejected():
    result = DuffelBookingProvider().reserve(
        ReservationRequest(booking_type="submarine", offer_id="x", idempotency_key="k")
    )
    assert not result.success
    assert "Unsupported booking type" in result.error
