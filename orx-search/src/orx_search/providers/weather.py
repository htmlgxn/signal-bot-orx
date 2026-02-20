from __future__ import annotations

import logging
from typing import Literal

from orx_search.base import SearchResult
from orx_search.http_client import AsyncHttpClient, HttpClient
from orx_search.registry import register

logger = logging.getLogger(__name__)


def _raise_http_error(status_code: int) -> None:
    raise RuntimeError(f"HTTP error {status_code}")


@register
class WeatherProvider:
    name = "weather"

    def __init__(
        self,
        api_key: str,
        units: Literal["metric", "imperial"] = "metric",
    ) -> None:
        self._api_key = api_key
        self._units = units
        self._base_url = "https://api.openweathermap.org/data/2.5"
        self._http_client = HttpClient(timeout=10)
        self._async_http_client: AsyncHttpClient | None = None

    def _get_async_client(self) -> AsyncHttpClient:
        if self._async_http_client is None:
            self._async_http_client = AsyncHttpClient(timeout=10)
        return self._async_http_client

    def search(self, query: str) -> list[SearchResult]:
        # Default search is current weather
        return self.current(query)

    def current(self, location: str) -> list[SearchResult]:
        """Get current weather for a location."""
        try:
            url = f"{self._base_url}/weather"
            params = {"q": location, "appid": self._api_key, "units": self._units}
            resp = self._http_client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return [self._format_current(data)]
        except Exception:
            logger.exception("Weather current search failed")
            return []

    def forecast(self, location: str) -> list[SearchResult]:
        """Get 5-day forecast for a location."""
        try:
            url = f"{self._base_url}/forecast"
            params = {"q": location, "appid": self._api_key, "units": self._units}
            resp = self._http_client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            return [self._format_forecast(data)]
        except Exception:
            logger.exception("Weather forecast search failed")
            return []

    async def current_async(self, location: str) -> list[SearchResult]:
        """Get current weather for a location (async)."""
        try:
            url = f"{self._base_url}/weather"
            params = {"q": location, "appid": self._api_key, "units": self._units}
            client = self._get_async_client()
            resp = await client.get(url, params=params)
            if resp.status_code >= 400:
                _raise_http_error(resp.status_code)

            import json

            data = json.loads(resp.text)
            return [self._format_current(data)]
        except Exception:
            logger.exception("Weather current async search failed")
            return []

    async def forecast_async(self, location: str) -> list[SearchResult]:
        """Get 5-day forecast for a location (async)."""
        try:
            url = f"{self._base_url}/forecast"
            params = {"q": location, "appid": self._api_key, "units": self._units}
            client = self._get_async_client()
            resp = await client.get(url, params=params)
            if resp.status_code >= 400:
                _raise_http_error(resp.status_code)

            import json

            data = json.loads(resp.text)
            return [self._format_forecast(data)]
        except Exception:
            logger.exception("Weather forecast async search failed")
            return []

    async def aclose(self) -> None:
        if self._async_http_client:
            await self._async_http_client.aclose()

    def _format_current(self, data: dict) -> SearchResult:
        city = data["name"]
        country = data["sys"].get("country", "")
        weather = data["weather"][0]["description"].capitalize()
        temp = data["main"]["temp"]
        feels = data["main"].get("feels_like")
        humidity = data["main"].get("humidity")
        wind = data["wind"].get("speed")

        snippet = (
            f"Condition: {weather}\n"
            f"Temperature: {temp}°{'C' if self._units == 'metric' else 'F'}\n"
            f"Feels like: {feels}°{'C' if self._units == 'metric' else 'F'}\n"
            f"Humidity: {humidity}%\n"
            f"Wind: {wind} m/s"
        )

        return SearchResult(
            title=f"Weather for {city}, {country}",
            url=f"https://openweathermap.org/city/{data['id']}",
            snippet=snippet,
            source="OpenWeatherMap",
        )

    def _format_forecast(self, data: dict) -> SearchResult:
        from datetime import datetime

        city = data["city"]["name"]
        country = data["city"].get("country", "")
        entries = data["list"]

        # Group by date, prefer 12:00
        daily: dict[str, dict] = {}
        for entry in entries:
            dt_txt = entry.get("dt_txt")
            if not dt_txt:
                continue
            dt = datetime.fromisoformat(dt_txt.replace(" ", "T"))
            date_key = dt.date().isoformat()
            hour = dt.hour
            if hour == 12 or date_key not in daily:
                daily[date_key] = entry

        lines = []
        for count, (date_str, entry) in enumerate(sorted(daily.items()), start=1):
            if count > 5:
                break
            weather = entry["weather"][0]["description"].capitalize()
            temp = entry["main"]["temp"]
            lines.append(
                f"{date_str}: {weather}, {temp}°{'C' if self._units == 'metric' else 'F'}"
            )

        return SearchResult(
            title=f"5-day forecast for {city}, {country}",
            url=f"https://openweathermap.org/city/{data['city']['id']}",
            snippet="\n".join(lines),
            source="OpenWeatherMap",
        )
