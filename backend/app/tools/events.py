"""Event search — Ticketmaster Discovery (primary) + Eventbrite (retired).

Events are SEARCH-ONLY by design: we surface deep links, never sell
tickets in-app (partner-gated, real money). Eventbrite retired its public
event-search endpoint in 2019 — the seam is kept so a partner token could
be wired later, but the tool degrades gracefully to Ticketmaster alone.
"""

import logging

import httpx
from pydantic import BaseModel, Field

from backend.app.config import settings
from backend.app.tools.base import BaseTool

logger = logging.getLogger(__name__)

_TICKETMASTER_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
_MAX_EVENTS = 5


class EventsInput(BaseModel):
    location: str            # city name
    keyword: str = ""        # optional interest keyword ("jazz", "baseball")


class Event(BaseModel):
    name: str
    date: str = ""           # local date, YYYY-MM-DD
    venue: str = ""
    url: str = ""            # deep link for booking on the partner site
    source: str = "ticketmaster"


class EventsResult(BaseModel):
    events: list[Event] = Field(default_factory=list)


class EventsTool(BaseTool[EventsInput, EventsResult]):
    latency_budget_s: float = 10.0

    def _run(self, input: EventsInput) -> EventsResult:  # noqa: A002
        if not settings.TICKETMASTER_API_KEY:
            raise ValueError("TICKETMASTER_API_KEY is not set")

        params = {
            "apikey": settings.TICKETMASTER_API_KEY,
            "city": input.location,
            "size": _MAX_EVENTS,
            "sort": "date,asc",
        }
        if input.keyword:
            params["keyword"] = input.keyword

        with httpx.Client(timeout=self.latency_budget_s) as client:
            resp = client.get(_TICKETMASTER_URL, params=params)
            resp.raise_for_status()

        raw_events = resp.json().get("_embedded", {}).get("events", [])
        events = []
        for ev in raw_events[:_MAX_EVENTS]:
            venues = ev.get("_embedded", {}).get("venues", [])
            events.append(
                Event(
                    name=ev.get("name", "Unnamed event"),
                    date=ev.get("dates", {}).get("start", {}).get("localDate", ""),
                    venue=venues[0].get("name", "") if venues else "",
                    url=ev.get("url", ""),
                )
            )
        logger.info(
            "EventsTool: %d event(s) for %s%s",
            len(events),
            input.location,
            f" (keyword={input.keyword})" if input.keyword else "",
        )
        # Eventbrite: public search API retired — deliberately not called.
        return EventsResult(events=events)
