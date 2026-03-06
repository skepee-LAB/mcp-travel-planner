"""
Travel Journey MCP Server
--------------------------
Exposes 4 tools to any MCP-compatible client (Claude, VS Code Copilot, etc.):

  1. get_coordinates   – resolve a city name to lat/lon
  2. get_weather       – current weather + 3-day forecast for a city
  3. get_place_info    – Wikipedia summary for a city/place
  4. get_currency_rate – EUR → target currency exchange rate

All APIs used are FREE and require NO API KEY:
  - Open-Meteo  (weather + geocoding): https://open-meteo.com
  - Wikipedia REST API:                https://en.wikipedia.org/api/rest_v1/
  - Open Exchange (frankfurter.app):   https://www.frankfurter.app
"""

import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Travel Journey Server")

# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────

def _geocode(city: str) -> dict:
    """Internal: resolve city → {lat, lon, name, country}"""
    url = "https://geocoding-api.open-meteo.com/v1/search"
    r = httpx.get(url, params={"name": city, "count": 1, "language": "en", "format": "json"}, timeout=10)
    r.raise_for_status()
    results = r.json().get("results")
    if not results:
        raise ValueError(f"City '{city}' not found.")
    top = results[0]
    return {
        "lat": top["latitude"],
        "lon": top["longitude"],
        "name": top["name"],
        "country": top.get("country", ""),
        "timezone": top.get("timezone", "UTC"),
    }

# ─────────────────────────────────────────────
# Tool 1 – Coordinates
# ─────────────────────────────────────────────

@mcp.tool()
def get_coordinates(city: str) -> dict:
    """
    Resolve a city name to geographic coordinates.
    Returns lat, lon, official name, country and timezone.

    Args:
        city: Name of the city (e.g. 'Paris', 'Tokyo', 'Buenos Aires')
    """
    return _geocode(city)

# ─────────────────────────────────────────────
# Tool 2 – Weather
# ─────────────────────────────────────────────

@mcp.tool()
def get_weather(city: str) -> dict:
    """
    Get current weather and 3-day daily forecast for a city.
    Includes temperature, wind, precipitation probability and weather description.

    Args:
        city: Name of the city (e.g. 'Rome', 'Bangkok')
    """
    geo = _geocode(city)

    WMO_CODES = {
        0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Icy fog",
        51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
        61: "Slight rain", 63: "Rain", 65: "Heavy rain",
        71: "Slight snow", 73: "Snow", 75: "Heavy snow",
        80: "Rain showers", 81: "Showers", 82: "Violent showers",
        95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Heavy thunderstorm",
    }

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": geo["lat"],
        "longitude": geo["lon"],
        "current": "temperature_2m,windspeed_10m,weathercode,precipitation,relative_humidity_2m",
        "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": geo["timezone"],
        "forecast_days": 4,
    }
    r = httpx.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    cur = data["current"]
    daily = data["daily"]

    forecast = []
    for i in range(1, 4):   # skip today (index 0), show next 3 days
        code = daily["weathercode"][i]
        forecast.append({
            "date": daily["time"][i],
            "condition": WMO_CODES.get(code, f"Code {code}"),
            "temp_max_c": daily["temperature_2m_max"][i],
            "temp_min_c": daily["temperature_2m_min"][i],
            "rain_probability_pct": daily["precipitation_probability_max"][i],
        })

    cur_code = cur["weathercode"]
    return {
        "city": geo["name"],
        "country": geo["country"],
        "current": {
            "condition": WMO_CODES.get(cur_code, f"Code {cur_code}"),
            "temperature_c": cur["temperature_2m"],
            "humidity_pct": cur["relative_humidity_2m"],
            "wind_kmh": cur["windspeed_10m"],
            "precipitation_mm": cur["precipitation"],
        },
        "forecast_3_days": forecast,
    }

# ─────────────────────────────────────────────
# Tool 3 – Place Info
# ─────────────────────────────────────────────

@mcp.tool()
def get_place_info(city: str) -> dict:
    """
    Get a structured summary of a city from Wikipedia.
    Returns title, extract (short description), and article URL.
    Great for travellers who want to know what a place is famous for.

    Args:
        city: Name of the city or place (e.g. 'Athens', 'Kyoto')
    """
    # Use Wikipedia REST summary endpoint – completely free, no key
    # User-Agent is required by Wikipedia's bot policy (https://w.wiki/4wJS)
    safe_city = city.strip().replace(" ", "_")
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{safe_city}"
    headers = {"User-Agent": "TravelJourneyMCPPlanner/1.0 (educational project)"}
    r = httpx.get(url, headers=headers, timeout=10, follow_redirects=True)

    if r.status_code == 404:
        return {"city": city, "summary": "No Wikipedia article found.", "url": ""}

    r.raise_for_status()
    data = r.json()

    return {
        "city": city,
        "title": data.get("title", city),
        "summary": data.get("extract", "No summary available."),
        "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
        "coordinates": data.get("coordinates", {}),
    }

# ─────────────────────────────────────────────
# Tool 4 – Currency Rate
# ─────────────────────────────────────────────

@mcp.tool()
def get_currency_rate(base_currency: str, target_currency: str) -> dict:
    """
    Get the latest exchange rate between two currencies.
    Useful for travel budget planning at each stop.
    Uses frankfurter.app – free, no key required.

    Args:
        base_currency:   ISO 4217 code, e.g. 'USD', 'EUR', 'GBP'
        target_currency: ISO 4217 code, e.g. 'JPY', 'THB', 'TRY'
    """
    base = base_currency.upper()
    target = target_currency.upper()
    url = f"https://api.frankfurter.app/latest"
    r = httpx.get(url, params={"from": base, "to": target}, timeout=10)
    r.raise_for_status()
    data = r.json()
    rate = data["rates"].get(target)
    return {
        "base": base,
        "target": target,
        "rate": rate,
        "date": data.get("date"),
        "meaning": f"1 {base} = {rate} {target}",
    }

# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # Run as stdio MCP server (default for local clients)
    mcp.run(transport="stdio")
