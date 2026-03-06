"""
Non-MCP journey logic — used by app.py for the side-by-side comparison.
Manually fetches all data for a hardcoded city list, dumps it all into a prompt.
This demonstrates the 'traditional' approach: no tool discovery, no LLM autonomy.
"""

import httpx
import json
import os
import re
import time
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors

load_dotenv()

BASE_CURRENCY = "EUR"
GEMINI_MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.0-flash-lite",
]

WIKIPEDIA_HEADERS = {"User-Agent": "TravelJourneyMCPPlanner/1.0 (educational project)"}

CURRENCY_MAP = {
    "France": "EUR", "Italy": "EUR", "Greece": "EUR",
    "Turkey": "TRY", "Japan": "JPY", "Thailand": "THB",
    "United Kingdom": "GBP", "United States": "USD",
    "United Arab Emirates": "AED", "Qatar": "QAR",
    "Argentina": "ARS", "Netherlands": "EUR",
}


def _geocode(city: str) -> dict:
    r = httpx.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": "en", "format": "json"},
        timeout=10,
    )
    results = r.json().get("results", [])
    if not results:
        raise ValueError(f"City not found: {city}")
    top = results[0]
    return {
        "lat": top["latitude"], "lon": top["longitude"],
        "timezone": top.get("timezone", "UTC"), "country": top.get("country", ""),
    }


def _fetch_weather(city: str, geo: dict) -> dict:
    r = httpx.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": geo["lat"], "longitude": geo["lon"],
            "current": "temperature_2m,windspeed_10m,weathercode,precipitation",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": geo["timezone"], "forecast_days": 4,
        },
        timeout=10,
    )
    return r.json()


def _fetch_place_info(city: str) -> str:
    r = httpx.get(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{city.replace(' ', '_')}",
        headers=WIKIPEDIA_HEADERS, timeout=10, follow_redirects=True,
    )
    if r.status_code == 200:
        return r.json().get("extract", "")[:600]
    return "No information found."


def _fetch_currency(target: str) -> dict:
    if target == BASE_CURRENCY:
        return {"from": BASE_CURRENCY, "to": target, "rate": 1.0}
    r = httpx.get(
        "https://api.frankfurter.app/latest",
        params={"from": BASE_CURRENCY, "to": target}, timeout=10,
    )
    data = r.json()
    return {"from": BASE_CURRENCY, "to": target, "rate": data["rates"].get(target)}


def _gemini_complete(prompt: str) -> tuple[str, int, int]:
    """Call Gemini with model fallback. Returns (text, input_tokens, output_tokens)."""
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    for model in GEMINI_MODELS:
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            return (
                response.text,
                response.usage_metadata.prompt_token_count or 0,
                response.usage_metadata.candidates_token_count or 0,
            )
        except genai_errors.ClientError as e:
            msg = str(e)
            if '429' in msg and 'limit: 0' in msg:
                continue   # try next model
            # parse retryDelay and wait if it's a transient 429
            if '429' in msg:
                delay_match = re.search(r'retry in (\d+)', msg)
                wait = int(delay_match.group(1)) + 2 if delay_match else 15
                time.sleep(wait)
                try:
                    response = client.models.generate_content(model=model, contents=prompt)
                    return (
                        response.text,
                        response.usage_metadata.prompt_token_count or 0,
                        response.usage_metadata.candidates_token_count or 0,
                    )
                except Exception:
                    continue
            raise
    raise RuntimeError(
        "All Gemini models quota exhausted. Please wait until midnight PT or add billing at https://aistudio.google.com"
    )


def run_without_mcp(cities: list[str]) -> dict:
    """
    Traditional approach: fetch ALL data for ALL cities upfront,
    dump everything into one giant prompt, send to LLM.

    Returns {answer, context_chars, steps, input_tokens, output_tokens}
    """
    steps = []   # track what was fetched and in what order

    all_data = []
    for city in cities:
        geo = _geocode(city)
        weather = _fetch_weather(city, geo)
        place = _fetch_place_info(city)
        currency_code = CURRENCY_MAP.get(geo["country"], "USD")
        currency = _fetch_currency(currency_code)

        steps.append({"city": city, "fetched": ["geocode", "weather", "place_info", "currency"]})
        all_data.append({
            "city": city,
            "country": geo["country"],
            "weather": weather,          # full raw JSON — no filtering!
            "place_info": place,
            "currency": currency,
        })

    # Dump EVERYTHING into the prompt regardless of what the LLM actually needs
    context = json.dumps(all_data, indent=2)

    prompt = f"""You are a travel assistant planning this journey: {' -> '.join(cities)}.

Here is ALL the pre-fetched data for every city (weather, place info, currency):

{context}

Based on this data please:
1. Give a brief travel overview of this journey
2. Highlight weather conditions at each stop
3. Note important cultural info
4. Give currency tips for each stop
5. Suggest a packing list based on the weather across all stops
"""

    answer, input_tokens, output_tokens = _gemini_complete(prompt)

    return {
        "answer": answer,
        "context_chars": len(context),
        "steps": steps,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
