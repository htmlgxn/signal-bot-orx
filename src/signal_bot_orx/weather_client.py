from __future__ import annotations

import asyncio
import logging
from typing import Literal

import httpx

logger = logging.getLogger(__name__)


class WeatherError(Exception):
    def __init__(self, user_message: str, *, status_code: int | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code


class OpenWeatherClient:
    """Simple client for OpenWeatherMap current weather and 5-day forecast.

    Uses the shared httpx.AsyncClient from the app to avoid extra connections.
    """

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient,
        units: Literal["metric", "imperial"] = "metric",
    ) -> None:
        self._api_key = api_key
        self._http_client = http_client
        self._units = units
        self._base_url = "https://api.openweathermap.org/data/2.5"

    async def current(self, location: str) -> dict:
        url = f"{self._base_url}/weather"
        params = {"q": location, "appid": self._api_key, "units": self._units}
        return await self._request(url, params)

    async def forecast(self, location: str) -> dict:
        url = f"{self._base_url}/forecast"
        params = {"q": location, "appid": self._api_key, "units": self._units}
        return await self._request(url, params)

    async def _request(self, url: str, params: dict) -> dict:
        for attempt in range(3):
            try:
                response = await self._http_client.get(url, params=params, timeout=10.0)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 2:
                    raise WeatherError("Weather service timed out. Try again.") from exc
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            if response.status_code < 400:
                try:
                    return response.json()
                except ValueError as exc:
                    raise WeatherError(
                        "Weather service returned invalid JSON.",
                        status_code=response.status_code,
                    ) from exc
            if response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            # Authorization or other client errors
            raise WeatherError(
                f"Weather request failed: {response.text}",
                status_code=response.status_code,
            )
        raise WeatherError("Weather request failed unexpectedly.")


def _format_current(data: dict, units: str) -> str:
    # Expected fields based on OpenWeatherMap API
    try:
        city = data["name"]
        country = data["sys"].get("country", "")
        weather = data["weather"][0]["description"].capitalize()
        temp = data["main"]["temp"]
        feels = data["main"].get("feels_like")
        humidity = data["main"].get("humidity")
        wind = data["wind"].get("speed")
    except (KeyError, IndexError, TypeError):
        return "Could not parse weather data."
    lines = [
        f"Weather for {city}, {country}:",
        f"- Condition: {weather}",
        f"- Temperature: {temp}°{'C' if units == 'metric' else 'F'}",
        f"- Feels like: {feels}°{'C' if units == 'metric' else 'F'}",
        f"- Humidity: {humidity}%",
        f"- Wind: {wind} m/s",
    ]
    return "\n".join([line for line in lines if line])


def _format_forecast(data: dict, units: str) -> str:
    # OpenWeatherMap returns a list of 3-hour forecasts. We'll pick one per day (12:00 local time).
    from datetime import datetime

    try:
        city = data["city"]["name"]
        country = data["city"].get("country", "")
        entries = data["list"]
    except (KeyError, TypeError):
        return "Could not parse forecast data."
    # Group by date
    daily: dict[str, dict] = {}
    for entry in entries:
        dt_txt = entry.get("dt_txt")
        if not dt_txt:
            continue
        dt = datetime.fromisoformat(dt_txt.replace(" ", "T"))
        date_key = dt.date().isoformat()
        # Prefer the entry at 12:00 if present, otherwise first entry of the day
        hour = dt.hour
        if hour == 12 or date_key not in daily:
            daily[date_key] = entry
    # Build output - limit to next 5 days
    lines = [f"5-day forecast for {city}, {country}:"]
    count = 0
    for date_str, entry in sorted(daily.items()):
        if count >= 5:
            break
        try:
            weather = entry["weather"][0]["description"].capitalize()
            temp = entry["main"]["temp"]
            lines.append(
                f"{date_str}: {weather}, {temp}°{'C' if units == 'metric' else 'F'}"
            )
            count += 1
        except (KeyError, IndexError, TypeError):
            continue
    return "\n".join(lines)
