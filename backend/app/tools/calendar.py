"""Calendar hold generation — .ics via icalendar, pure code, no LLM.

The low-risk half of the Action agent's risk tiering: generating a
calendar file writes nothing external and needs no key, so it happens
automatically (no confirmation gate). The caller decides what to do
with the returned .ics text (the API ships it in the done payload).
"""

import logging
from datetime import datetime, timedelta

from icalendar import Calendar, Event

logger = logging.getLogger(__name__)


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def build_trip_ics(
    location: str,
    flight: dict | None = None,
    restaurant: dict | None = None,
) -> str | None:
    """Build an .ics calendar hold for the trip. Returns None if there is
    nothing datable to put on a calendar."""
    cal = Calendar()
    cal.add("prodid", "-//WanderWise//Trip Hold//EN")
    cal.add("version", "2.0")
    events = 0

    departure = _parse_dt((flight or {}).get("departure_at", ""))
    if departure:
        event = Event()
        event.add("summary", f"Flight to {location} ({flight.get('carrier', 'TBD')})")
        event.add("dtstart", departure)
        arrival = _parse_dt(flight.get("arrival_at", ""))
        event.add("dtend", arrival or departure + timedelta(hours=2))
        event.add("uid", f"wanderwise-flight-{flight.get('offer_id', 'tbd')}")
        cal.add_component(event)
        events += 1

    slot = _parse_dt((restaurant or {}).get("slot", ""))
    if slot:
        event = Event()
        event.add("summary", f"Dinner at {restaurant.get('name', 'restaurant')} — {location}")
        event.add("dtstart", slot)
        event.add("dtend", slot + timedelta(hours=2))
        event.add("uid", f"wanderwise-restaurant-{restaurant.get('venue_id', 'tbd')}")
        cal.add_component(event)
        events += 1

    if not events:
        return None
    logger.info("Calendar hold built: %d event(s) for %s", events, location)
    return cal.to_ical().decode()
