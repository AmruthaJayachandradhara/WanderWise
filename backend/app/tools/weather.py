"""Weather tool — Open-Meteo forecast + Nominatim geocoding.

Both APIs are free, no key required.
Nominatim: max 1 req/sec per their usage policy; we set a descriptive User-Agent.
Open-Meteo: no hard rate limit for non-commercial use.

On any upstream failure, BaseTool.run() returns a degraded ToolResult
rather than raising — the orchestrator handles unavailability gracefully.
"""

import logging
import time

import httpx
from pydantic import BaseModel

from backend.app.tools.base import BaseTool

logger = logging.getLogger(__name__)

# Nominatim requires a descriptive User-Agent identifying the application
_NOMINATIM_UA = "WanderWise/0.1 (portfolio-project; amruthajayachandra.dhara@gmail.com)"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO weather interpretation codes → readable description
_WMO_CODES: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight showers", 81: "Moderate showers", 82: "Violent showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


# --- Schema ---

class WeatherInput(BaseModel):
    location: str
    days: int = 7  # forecast horizon (1–16 days)


class DayForecast(BaseModel):
    date: str
    max_temp_c: float
    min_temp_c: float
    precipitation_mm: float
    description: str


class WeatherForecast(BaseModel):
    location: str
    latitude: float
    longitude: float
    daily: list[DayForecast]


# --- Implementation ---

class WeatherTool(BaseTool[WeatherInput, WeatherForecast]):
    latency_budget_s: float = 5.0

    def _run(self, input: WeatherInput) -> WeatherForecast:  # noqa: A002
        lat, lon = self._geocode(input.location)
        return self._forecast(input.location, lat, lon, input.days)

    def _geocode(self, location: str) -> tuple[float, float]:
        """Resolve a city name to (lat, lon) via Nominatim."""
        # Respect Nominatim's 1 req/sec policy
        time.sleep(1)
        with httpx.Client(timeout=10) as client:
            resp = client.get(
                _NOMINATIM_URL,
                params={"q": location, "format": "json", "limit": 1},
                headers={"User-Agent": _NOMINATIM_UA},
            )
            resp.raise_for_status()
        results = resp.json()
        if not results:
            raise ValueError(f"Location not found: {location!r}")
        return float(results[0]["lat"]), float(results[0]["lon"])

    def _forecast(
        self, location: str, lat: float, lon: float, days: int
    ) -> WeatherForecast:
        """Fetch a daily forecast from Open-Meteo."""
        params = {
            "latitude": lat,
            "longitude": lon,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
            "forecast_days": min(days, 16),
            "timezone": "auto",
        }
        with httpx.Client(timeout=10) as client:
            resp = client.get(_OPEN_METEO_URL, params=params)
            resp.raise_for_status()
        data = resp.json()["daily"]

        daily = [
            DayForecast(
                date=data["time"][i],
                max_temp_c=data["temperature_2m_max"][i],
                min_temp_c=data["temperature_2m_min"][i],
                precipitation_mm=data["precipitation_sum"][i],
                description=_WMO_CODES.get(data["weathercode"][i], "Unknown"),
            )
            for i in range(len(data["time"]))
        ]
        return WeatherForecast(location=location, latitude=lat, longitude=lon, daily=daily)
