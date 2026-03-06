"""
WITHOUT MCP – Traditional approach to travel journey planning
--------------------------------------------------------------
Problems this demonstrates:
  ❌ You manually call every API yourself
  ❌ You must know in advance WHICH data to fetch for WHICH cities
  ❌ ALL data is dumped into the prompt (wastes tokens, hits context limits)
  ❌ No reusability – another app must duplicate all this code
  ❌ LLM cannot ask for more data if needed – it only sees what you pre-fetched
  ❌ Adding a new data source = editing this file everywhere
"""

import httpx
import json
import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

# ── Configuration ────────────────────────────────────────────────
JOURNEY = ["Paris", "Rome", "Athens", "Istanbul"]
BASE_CURRENCY = "EUR"

gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
GEMINI_MODEL = "gemini-2.0-flash"

# ── Step 1: Manually geocode every city ─────────────────────────
def geocode(city: str) -> dict:
    r = httpx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=10,
    )
    results = r.json().get("results", [])
    if not results:
        raise ValueError(f"City not found: {city}")
    top = results[0]
    return {"lat": top["latitude"], "lon": top["longitude"], "timezone": top.get("timezone", "UTC"), "country": top.get("country", "")}

# ── Step 2: Manually fetch weather for every city ───────────────
def fetch_weather(city: str, geo: dict) -> dict:
    r = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": geo["lat"],
            "longitude": geo["lon"],
            "current": "temperature_2m,windspeed_10m,weathercode,precipitation",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": geo["timezone"],
            "forecast_days": 4,
        },
        timeout=10,
    )
    return {"city": city, "weather": r.json()}

# ── Step 3: Manually fetch Wikipedia for every city ─────────────
def fetch_place_info(city: str) -> dict:
    r = httpx.get(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{city.replace(' ', '_')}",
        timeout=10,
        follow_redirects=True,
    )
    if r.status_code == 200:
        data = r.json()
        return {"city": city, "summary": data.get("extract", "")[:500]}  # truncate to save tokens
    return {"city": city, "summary": "Not found"}

# ── Step 4: Manually fetch currency rates for every destination ──
def fetch_currency(target: str) -> dict:
    r = httpx.get(
        "https://api.frankfurter.app/latest",
        params={"from": BASE_CURRENCY, "to": target},
        timeout=10,
    )
    data = r.json()
    return {"from": BASE_CURRENCY, "to": target, "rate": data["rates"].get(target)}

CURRENCY_MAP = {
    "France":  "EUR",
    "Italy":   "EUR",
    "Greece":  "EUR",
    "Turkey":  "TRY",
    "Japan":   "JPY",
    "Thailand": "THB",
    "United Kingdom": "GBP",
    "United States": "USD",
}

# ── Main: fetch EVERYTHING upfront, blindly ─────────────────────
def build_context() -> str:
    print("📡 Fetching data for all cities manually...\n")
    all_data = []

    for city in JOURNEY:
        print(f"  🔍 {city}...")
        geo = geocode(city)
        weather = fetch_weather(city, geo)
        place = fetch_place_info(city)
        currency_code = CURRENCY_MAP.get(geo["country"], "USD")
        currency = fetch_currency(currency_code) if currency_code != BASE_CURRENCY else {"from": "EUR", "to": "EUR", "rate": 1.0}

        all_data.append({
            "city": city,
            "country": geo["country"],
            "weather": weather["weather"],   # ← full raw JSON dumped in!
            "place_info": place["summary"],
            "currency": currency,
        })

    # Dump everything as raw JSON into the prompt
    return json.dumps(all_data, indent=2)

def main():
    context = build_context()

    print("\n" + "="*60)
    print(f"📦 Total context size: {len(context):,} characters being sent to LLM")
    print("="*60 + "\n")

    prompt = f"""
You are a travel assistant. The user wants to travel: {' → '.join(JOURNEY)}.

Here is ALL the pre-fetched data for every city (weather, place info, currency):

{context}

Based on this data, please:
1. Give a brief travel overview of this journey
2. Highlight the weather conditions at each stop
3. Note any important cultural info
4. Give a currency tip for each stop
5. Suggest the best packing list based on weather across all stops
"""

    print("🤖 Sending to Gemini...\n")
    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )

    print("✈️  TRAVEL PLAN (without MCP)\n")
    print(response.text)
    print(f"\n📊 Tokens used – Input: {response.usage_metadata.prompt_token_count} | Output: {response.usage_metadata.candidates_token_count}")

if __name__ == "__main__":
    main()
