"""Offline unit tests for the mock reservation service (Phase 4 Step 2).

Exercises the FastAPI app over real HTTP semantics (TestClient) plus the
mock provider end-to-end through its in-process ASGI transport. No network.
"""

import pytest
from fastapi.testclient import TestClient

from backend.app.booking.mock_provider import MockBookingProvider
from backend.app.booking.provider import ReservationRequest
from backend.app.reservation_service.service import app, store

client = TestClient(app)

_BODY = {
    "venue_id": "osm:node/123",
    "venue_name": "Sushi Saito",
    "slot": "2026-08-01T19:00",
    "party_size": 2,
}


@pytest.fixture(autouse=True)
def _clean_store():
    store.reset()
    yield
    store.reset()


def _reserve(key: str = "key-1", **overrides):
    return client.post(
        "/reservations",
        json={**_BODY, **overrides},
        headers={"Idempotency-Key": key},
    )


# ---------------------------------------------------------------------------
# Service semantics
# ---------------------------------------------------------------------------

def test_reserve_returns_reservation_id():
    resp = _reserve()
    assert resp.status_code == 201
    body = resp.json()
    assert body["reservation_id"].startswith("res_")
    assert body["status"] == "reserved"
    assert body["confirmation_id"] is None


def test_duplicate_idempotency_key_returns_same_reservation():
    first = _reserve(key="dup").json()
    replay = _reserve(key="dup")
    assert replay.status_code == 200  # replay, not a new resource
    assert replay.json()["reservation_id"] == first["reservation_id"]


def test_conflicting_slot_rejected_with_409():
    _reserve(key="a")
    conflict = _reserve(key="b")  # same venue + slot, different key
    assert conflict.status_code == 409
    assert "already reserved" in conflict.json()["detail"]


def test_different_slot_same_venue_is_fine():
    _reserve(key="a")
    ok = _reserve(key="b", slot="2026-08-01T21:00")
    assert ok.status_code == 201


def test_confirm_mints_confirmation_id():
    rid = _reserve().json()["reservation_id"]
    resp = client.post(f"/reservations/{rid}/confirm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "confirmed"
    assert body["confirmation_id"].startswith("WW-")
    # Confirm is idempotent — same ID on replay
    assert client.post(f"/reservations/{rid}/confirm").json()["confirmation_id"] == body["confirmation_id"]


def test_cancel_rolls_back_and_frees_slot():
    rid = _reserve(key="a").json()["reservation_id"]
    resp = client.delete(f"/reservations/{rid}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    # Slot is free again for another party
    assert _reserve(key="b").status_code == 201


def test_confirm_cancelled_reservation_rejected():
    rid = _reserve().json()["reservation_id"]
    client.delete(f"/reservations/{rid}")
    assert client.post(f"/reservations/{rid}/confirm").status_code == 409


def test_unknown_reservation_404s():
    assert client.get("/reservations/res_nope").status_code == 404
    assert client.post("/reservations/res_nope/confirm").status_code == 404
    assert client.delete("/reservations/res_nope").status_code == 404


def test_availability_endpoint():
    q = {"venue_id": _BODY["venue_id"], "slot": _BODY["slot"]}
    assert client.get("/availability", params=q).json()["available"] is True
    _reserve()
    assert client.get("/availability", params=q).json()["available"] is False


# ---------------------------------------------------------------------------
# Mock provider → service, through the BookingProvider contract
# ---------------------------------------------------------------------------

def _req(key: str = "prov-key") -> ReservationRequest:
    return ReservationRequest(
        booking_type="restaurant",
        offer_id=_BODY["venue_id"],
        idempotency_key=key,
        details={"slot": _BODY["slot"], "party_size": 2, "venue_name": _BODY["venue_name"]},
    )


def test_provider_reserve_confirm_cancel_roundtrip():
    provider = MockBookingProvider()

    reserved = provider.reserve(_req())
    assert reserved.success
    rid = reserved.data.reservation_id

    confirmed = provider.confirm(rid)
    assert confirmed.success
    assert confirmed.data.confirmation_id.startswith("WW-")

    cancelled = provider.cancel(rid)
    assert cancelled.success
    assert cancelled.data.status == "cancelled"


def test_provider_idempotent_reserve():
    provider = MockBookingProvider()
    first = provider.reserve(_req(key="same"))
    second = provider.reserve(_req(key="same"))
    assert first.data.reservation_id == second.data.reservation_id


def test_provider_conflict_is_clean_failure_not_degraded():
    provider = MockBookingProvider()
    assert provider.reserve(_req(key="a")).success
    conflict = provider.reserve(_req(key="b"))
    assert not conflict.success
    assert not conflict.degraded  # business rejection, not an outage
    assert "already reserved" in conflict.error
