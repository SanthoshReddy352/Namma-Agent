"""Weather tool — current conditions for a place. Keyless, stdlib-only.

Two small HTTPS calls, no API key:
  1. Geocode the location via Nominatim (OpenStreetMap).
  2. Fetch current conditions from Open-Meteo.

Results are cached on disk for 24h (``~/.cache/friday/weather``) so repeat
queries don't hammer the public services. Ported from ``modules/weather`` but
self-contained — uses ``urllib`` instead of ``requests``.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

from friday.core.logger import logger
from friday.core.tools import ToolRegistry, ToolResult

_USER_AGENT = "FRIDAY-Linux-Weather/2.0"
_CACHE_TTL_S = 24 * 60 * 60
_TIMEOUT = 6

# WMO weather codes (truncated to what we surface). https://open-meteo.com/en/docs
_CODE_TEXT = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "depositing rime fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "dense drizzle",
    61: "light rain", 63: "moderate rain", 65: "heavy rain",
    71: "light snow", 73: "moderate snow", 75: "heavy snow", 77: "snow grains",
    80: "rain showers", 81: "moderate rain showers", 82: "violent rain showers",
    85: "snow showers", 86: "heavy snow showers",
    95: "thunderstorm", 96: "thunderstorm with light hail", 99: "thunderstorm with heavy hail",
}


def _cache_path(name: str) -> str:
    base = os.path.join(os.path.expanduser("~"), ".cache", "friday", "weather")
    os.makedirs(base, exist_ok=True)
    key = "_".join((name or "").strip().lower().split()) or "_default"
    return os.path.join(base, f"{key}.json")


def _read_cache(name: str) -> dict | None:
    path = _cache_path(name)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception:  # noqa: BLE001
        return None
    if (time.time() - payload.get("saved_at", 0)) > _CACHE_TTL_S:
        return None
    return payload


def _write_cache(name: str, payload: dict) -> None:
    payload = {**payload, "saved_at": time.time()}
    try:
        with open(_cache_path(name), "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[weather] cache write failed: %s", exc)


def _get_json(url: str, params: dict):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _geocode(location: str) -> dict:
    data = _get_json("https://nominatim.openstreetmap.org/search",
                     {"q": location, "format": "json", "limit": 1, "addressdetails": 1})
    if not isinstance(data, list) or not data:
        raise ValueError(f"couldn't find a place matching {location!r}")
    first = data[0]
    addr = first.get("address", {}) if isinstance(first, dict) else {}
    return {
        "name": first.get("display_name", location).split(",")[0].strip(),
        "country": addr.get("country", "") if isinstance(addr, dict) else "",
        "lat": float(first["lat"]), "lon": float(first["lon"]),
    }


def _weather(args: dict) -> ToolResult:
    location = (args.get("location") or "").strip()
    if not location:
        return ToolResult(ok=False, content="", error="a location is required")

    cached = _read_cache(location)
    if cached and "report" in cached:
        return ToolResult(ok=True, content=cached["report"], data=cached.get("data"))

    try:
        geo = _geocode(location)
        data = _get_json("https://api.open-meteo.com/v1/forecast", {
            "latitude": geo["lat"], "longitude": geo["lon"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
            "wind_speed_unit": "kmh",
        })
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"weather lookup failed: {exc}")

    cur = data.get("current", {}) if isinstance(data, dict) else {}
    if not cur:
        return ToolResult(ok=False, content="", error="no current-conditions data returned")
    code = int(cur.get("weather_code", 0))
    place = geo["name"] + (f", {geo['country']}" if geo["country"] and geo["country"].lower() not in geo["name"].lower() else "")
    report = (
        f"Weather in {place}: {_CODE_TEXT.get(code, f'code {code}')}, "
        f"{cur.get('temperature_2m')}°C (feels like {cur.get('apparent_temperature')}°C), "
        f"humidity {cur.get('relative_humidity_2m')}%, wind {cur.get('wind_speed_10m')} km/h."
    )
    payload = {"report": report, "data": {"place": place, "temperature_c": cur.get("temperature_2m"),
                                          "weather_code": code, "description": _CODE_TEXT.get(code)}}
    _write_cache(location, payload)
    return ToolResult(ok=True, content=report, data=payload["data"])


def register(registry: ToolRegistry) -> None:
    registry.register("get_weather", "Get current weather for a place (keyless, Open-Meteo).", {
        "type": "object",
        "properties": {"location": {"type": "string", "description": "city/place name, e.g. 'Mumbai'"}},
        "required": ["location"],
    }, _weather)
