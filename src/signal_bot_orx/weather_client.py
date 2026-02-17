import logging
from typing import Literal

import httpx
from orx_search.providers.weather import WeatherProvider

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)


class WeatherError(Exception):
    def __init__(self, user_message: str, *, status_code: int | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.status_code = status_code


class OpenWeatherClient:
    """Client for OpenWeatherMap wrapping orx-search WeatherProvider."""

    def __init__(
        self,
        *,
        api_key: str,
        http_client: httpx.AsyncClient | None = None,
        units: Literal["metric", "imperial"] = "metric",
    ) -> None:
        _ = http_client  # Unused, kept for compatibility
        self._provider = WeatherProvider(api_key=api_key, units=units)

    async def current(self, location: str) -> dict:
        """Get current weather raw data for compatibility with _format_current."""
        # For compatibility with webhook.py, we still need raw dict if we keep _format_current there.
        # But WeatherProvider.current_async returns SearchResult.
        # Let's adjust it to return raw if needed, or just re-request or use private method.
        # Actually, WeatherProvider already has _get_current (sync) and current_async.
        # I'll make _get_current_data_async available in WeatherProvider.

        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": location,
            "appid": self._provider._api_key,
            "units": self._provider._units,
        }
        client = self._provider._get_async_client()
        resp = await client.get(url, params=params)
        if resp.status_code >= 400:
            raise WeatherError(
                f"Weather request failed: {resp.text}", status_code=resp.status_code
            )
        return resp.json()

    async def forecast(self, location: str) -> dict:
        """Get forecast raw data for compatibility with _format_forecast."""
        url = "https://api.openweathermap.org/data/2.5/forecast"
        params = {
            "q": location,
            "appid": self._provider._api_key,
            "units": self._provider._units,
        }
        client = self._provider._get_async_client()
        resp = await client.get(url, params=params)
        if resp.status_code >= 400:
            raise WeatherError(
                f"Weather request failed: {resp.text}", status_code=resp.status_code
            )
        return resp.json()


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
