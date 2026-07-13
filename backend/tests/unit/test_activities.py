"""Offline unit tests for the Activities subagent + places/events tools
(Phase 4 Step 6). All network and LLM calls are monkeypatched.
"""

import json

import httpx
import pytest

import backend.app.agents.activities_booking as act_module
from backend.app.agents.activities_booking import activities_node
from backend.app.llm.base import LLMResponse
from backend.app.tools.events import EventsInput, EventsTool
from backend.app.tools.places import PlacesInput, PlacesTool

_OVERPASS_RESPONSE = {
    "elements": [
        {
            "id": 111,
            "lat": 35.66,
            "lon": 139.73,
            "tags": {"name": "Sushi Saito", "amenity": "restaurant", "cuisine": "sushi"},
        },
        {
            "id": 222,
            "lat": 35.67,
            "lon": 139.74,
            "tags": {"name": "Ramen Ichiran", "amenity": "restaurant", "cuisine": "ramen"},
        },
    ]
}

_TICKETMASTER_RESPONSE = {
    "_embedded": {
        "events": [
            {
                "name": "Yomiuri Giants vs Tigers",
                "url": "https://tm.example/e/1",
                "dates": {"start": {"localDate": "2026-08-16"}},
                "_embedded": {"venues": [{"name": "Tokyo Dome"}]},
            }
        ]
    }
}


def _mock_httpx(monkeypatch, module, response_json, status=200):
    class _Resp:
        status_code = status

        def json(self):
            return response_json

        def raise_for_status(self):
            if status >= 400:
                raise httpx.HTTPStatusError("err", request=None, response=None)

    class _Client:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **kw):
            return _Resp()

        def post(self, *a, **kw):
            return _Resp()

    monkeypatch.setattr(module, "Client", _Client)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class TestPlacesTool:
    def test_parses_overpass_elements(self, monkeypatch):
        import backend.app.tools.places as places_module

        monkeypatch.setattr(places_module, "geocode", lambda city: (35.68, 139.69))
        _mock_httpx(monkeypatch, places_module.httpx, _OVERPASS_RESPONSE)

        result = PlacesTool().run(PlacesInput(location="Tokyo", cuisine="sushi"))
        assert result.success
        places = result.data.places
        assert places[0].venue_id == "osm:node/111"
        assert places[0].name == "Sushi Saito"
        assert places[0].cuisine == "sushi"

    def test_unknown_category_degrades(self):
        result = PlacesTool().run(PlacesInput(location="Tokyo", category="spaceport"))
        assert not result.success
        assert result.degraded


class TestEventsTool:
    def test_parses_ticketmaster_events(self, monkeypatch):
        import backend.app.tools.events as events_module

        monkeypatch.setattr(events_module.settings, "TICKETMASTER_API_KEY", "tm-key")
        _mock_httpx(monkeypatch, events_module.httpx, _TICKETMASTER_RESPONSE)

        result = EventsTool().run(EventsInput(location="Tokyo", keyword="baseball"))
        assert result.success
        events = result.data.events
        assert events[0].name == "Yomiuri Giants vs Tigers"
        assert events[0].venue == "Tokyo Dome"
        assert events[0].url.startswith("https://tm.example")

    def test_missing_key_degrades(self, monkeypatch):
        import backend.app.tools.events as events_module

        monkeypatch.setattr(events_module.settings, "TICKETMASTER_API_KEY", None)
        result = EventsTool().run(EventsInput(location="Tokyo"))
        assert not result.success
        assert result.degraded
        assert "TICKETMASTER_API_KEY" in result.error


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

@pytest.fixture
def fresh_cache(monkeypatch):
    store = {}
    monkeypatch.setattr(act_module, "api_get", store.get)
    monkeypatch.setattr(
        act_module, "api_set", lambda k, v, ttl=0: store.__setitem__(k, v)
    )
    return store


def _fake_llm(monkeypatch, by_tier: dict):
    def complete(tier, messages, **kw):
        return LLMResponse(
            text=by_tier[tier], tier=tier, model="fake",
            input_tokens=0, output_tokens=0, latency_ms=1.0,
        )

    monkeypatch.setattr(act_module.llm, "complete", complete)


def _tool_results(monkeypatch, restaurants=_OVERPASS_RESPONSE, events=True):
    from backend.app.tools.base import ToolResult
    from backend.app.tools.events import Event, EventsResult
    from backend.app.tools.places import Place, PlacesResult

    places = PlacesResult(
        places=[
            Place(
                venue_id=f"osm:node/{el['id']}",
                name=el["tags"]["name"],
                category="restaurant",
                cuisine=el["tags"].get("cuisine", ""),
                latitude=el["lat"],
                longitude=el["lon"],
            )
            for el in (restaurants or {}).get("elements", [])
        ]
    )
    monkeypatch.setattr(
        act_module._places_tool,
        "run",
        lambda inp: ToolResult(success=restaurants is not None, data=places if restaurants else None, error=None if restaurants else "overpass down", degraded=restaurants is None),
    )
    ev_result = EventsResult(events=[Event(name="Giants game", date="2026-08-16", venue="Tokyo Dome", url="https://tm.example/e/1")])
    monkeypatch.setattr(
        act_module._events_tool,
        "run",
        lambda inp: ToolResult(success=events, data=ev_result if events else None, error=None if events else "tm down", degraded=not events),
    )


class TestActivitiesNode:
    def test_happy_path_selects_candidate(self, monkeypatch, fresh_cache):
        _fake_llm(monkeypatch, {
            "small": '{"cuisine": "sushi", "event_keyword": "baseball", "party_size": 2}',
            "large": '{"venue_id": "osm:node/111", "name": "Sushi Saito", "slot": "2026-08-16T19:00", "party_size": 2, "reason": "cuisine match"}',
        })
        _tool_results(monkeypatch)
        result = activities_node({"location": "Tokyo", "query": "sushi trip", "interests": ["food"]})
        assert len(result["restaurants"]) == 2
        assert result["events"][0]["name"] == "Giants game"
        assert result["selected_restaurant"]["venue_id"] == "osm:node/111"
        assert result["selected_restaurant"]["slot"] == "2026-08-16T19:00"
        assert result["activities_degraded"] is False

    def test_selection_hallucinated_venue_falls_back_to_first(self, monkeypatch, fresh_cache):
        _fake_llm(monkeypatch, {
            "small": '{"cuisine": null, "event_keyword": null, "party_size": 2}',
            "large": '{"venue_id": "osm:node/999", "name": "Fake Place", "slot": "2026-08-16T19:00"}',
        })
        _tool_results(monkeypatch)
        result = activities_node({"location": "Tokyo", "query": "trip"})
        assert result["selected_restaurant"]["venue_id"] == "osm:node/111"
        assert "fallback" in result["selected_restaurant"]["reason"]

    def test_both_sources_degraded(self, monkeypatch, fresh_cache):
        _fake_llm(monkeypatch, {
            "small": '{"cuisine": null, "event_keyword": null, "party_size": 2}',
            "large": "unused",
        })
        _tool_results(monkeypatch, restaurants=None, events=False)
        result = activities_node({"location": "Tokyo", "query": "trip"})
        assert result["restaurants"] is None
        assert result["events"] is None
        assert result["selected_restaurant"] is None
        assert result["activities_degraded"] is True

    def test_no_location_skips(self):
        result = activities_node({"query": "trip"})
        assert result["activities_degraded"] is True

    def test_restaurants_cached_by_location_and_cuisine(self, monkeypatch, fresh_cache):
        _fake_llm(monkeypatch, {
            "small": '{"cuisine": "sushi", "event_keyword": null, "party_size": 2}',
            "large": '{"venue_id": "osm:node/111", "name": "Sushi Saito", "slot": "2026-08-16T19:00"}',
        })
        _tool_results(monkeypatch)
        activities_node({"location": "Tokyo", "query": "sushi"})
        assert "places:v1:tokyo:sushi" in fresh_cache
        cached = json.loads(fresh_cache["places:v1:tokyo:sushi"])
        assert cached[0]["name"] == "Sushi Saito"
