"""Offline unit tests for the BookingProvider abstraction (Phase 4 Step 1).

No network, no live providers — only the factory routing and the contract.
"""

import pytest

from backend.app.booking import provider as provider_mod
from backend.app.booking.duffel_provider import DuffelBookingProvider
from backend.app.booking.mock_provider import MockBookingProvider
from backend.app.booking.provider import BookingProvider, get_provider


@pytest.fixture(autouse=True)
def _reset_provider_singletons():
    provider_mod._instances.clear()
    yield
    provider_mod._instances.clear()


def test_flight_routes_to_duffel():
    p = get_provider("flight")
    assert isinstance(p, DuffelBookingProvider)
    assert "flight" in p.booking_types


def test_hotel_routes_to_duffel():
    assert isinstance(get_provider("hotel"), DuffelBookingProvider)


def test_restaurant_routes_to_mock():
    p = get_provider("restaurant")
    assert isinstance(p, MockBookingProvider)
    assert p.booking_types == ("restaurant",)


def test_unknown_booking_type_raises():
    with pytest.raises(ValueError, match="No booking provider configured"):
        get_provider("submarine")


def test_unknown_provider_name_raises(monkeypatch):
    monkeypatch.setitem(
        provider_mod.settings.BOOKING_PROVIDER_MAP, "restaurant", "opentable"
    )
    with pytest.raises(ValueError, match="Unknown booking provider"):
        get_provider("restaurant")


def test_provider_is_cached_singleton():
    assert get_provider("flight") is get_provider("hotel")


def test_backends_satisfy_the_protocol():
    assert isinstance(DuffelBookingProvider(), BookingProvider)
    assert isinstance(MockBookingProvider(), BookingProvider)
