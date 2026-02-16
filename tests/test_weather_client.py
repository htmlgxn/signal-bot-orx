from __future__ import annotations

from signal_bot_orx.weather_client import _format_current, _format_forecast


def test_format_current_metric() -> None:
    data = {
        "name": "London",
        "sys": {"country": "GB"},
        "weather": [{"description": "light rain"}],
        "main": {"temp": 10.5, "feels_like": 9.0, "humidity": 85},
        "wind": {"speed": 5.5},
    }
    out = _format_current(data, "metric")
    assert "Weather for London, GB:" in out
    assert "- Condition: Light rain" in out
    assert "- Temperature: 10.5°C" in out
    assert "- Feels like: 9.0°C" in out
    assert "- Humidity: 85%" in out
    assert "- Wind: 5.5 m/s" in out


def test_format_current_imperial() -> None:
    data = {
        "name": "Paris",
        "sys": {"country": "FR"},
        "weather": [{"description": "sunny"}],
        "main": {"temp": 50.0, "feels_like": 48.0, "humidity": 40},
        "wind": {"speed": 3.0},
    }
    out = _format_current(data, "imperial")
    assert "Weather for Paris, FR:" in out
    assert "- Condition: Sunny" in out
    assert "- Temperature: 50.0°F" in out
    assert "- Feels like: 48.0°F" in out


def test_format_current_missing_fields() -> None:
    data = {"name": "Nowhere"}
    out = _format_current(data, "metric")
    assert out == "Could not parse weather data."


def test_format_forecast_five_days_metric() -> None:
    # Simulate a forecast response with multiple entries per day
    city = {"name": "Tokyo", "country": "JP"}
    entries = [
        {
            "dt_txt": "2025-02-16 00:00:00",
            "weather": [{"description": "clear"}],
            "main": {"temp": 5},
        },
        {
            "dt_txt": "2025-02-16 12:00:00",
            "weather": [{"description": "sunny"}],
            "main": {"temp": 10},
        },
        {
            "dt_txt": "2025-02-17 03:00:00",
            "weather": [{"description": "cloudy"}],
            "main": {"temp": 7},
        },
        {
            "dt_txt": "2025-02-18 12:00:00",
            "weather": [{"description": "rain"}],
            "main": {"temp": 8},
        },
        {
            "dt_txt": "2025-02-19 12:00:00",
            "weather": [{"description": "storm"}],
            "main": {"temp": 6},
        },
        {
            "dt_txt": "2025-02-20 12:00:00",
            "weather": [{"description": "snow"}],
            "main": {"temp": 0},
        },
    ]
    data = {"city": city, "list": entries}
    out = _format_forecast(data, "metric")
    assert "5-day forecast for Tokyo, JP:" in out
    assert "2025-02-16: Sunny, 10°C" in out
    assert "2025-02-17: Cloudy, 7°C" in out
    assert "2025-02-18: Rain, 8°C" in out
    assert "2025-02-19: Storm, 6°C" in out
    assert "2025-02-20: Snow, 0°C" in out


def test_format_forecast_imperial() -> None:
    city = {"name": "New York", "country": "US"}
    entries = [
        {
            "dt_txt": "2025-02-16 12:00:00",
            "weather": [{"description": "sunny"}],
            "main": {"temp": 50},
        }
    ]
    data = {"city": city, "list": entries}
    out = _format_forecast(data, "imperial")
    assert "5-day forecast for New York, US:" in out
    assert "2025-02-16: Sunny, 50°F" in out


def test_format_forecast_malformed() -> None:
    data = {}
    out = _format_forecast(data, "metric")
    assert out == "Could not parse forecast data."
