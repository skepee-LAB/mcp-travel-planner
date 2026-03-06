"""
Flask web interface for the MCP Travel Journey Planner.
Run with: python app.py
Then open: http://localhost:5000
"""

import os
import re
from flask import Flask, render_template, request, jsonify
from mcp_core import run_journey_sync
from without_mcp_core import run_without_mcp

app = Flask(__name__)

# Cities we recognise for the non-MCP mode (extend as needed)
KNOWN_CITIES = [
    "Paris", "Rome", "Athens", "Istanbul", "London", "Tokyo", "Dubai",
    "New York", "Miami", "Buenos Aires", "Amsterdam", "Bangkok", "Doha",
    "Barcelona", "Berlin", "Vienna", "Prague", "Budapest", "Lisbon",
    "Madrid", "Dublin", "Brussels", "Copenhagen", "Stockholm", "Oslo",
    "Helsinki", "Warsaw", "Kyiv", "Bucharest", "Sofia", "Belgrade",
    "Zurich", "Geneva", "Munich", "Hamburg", "Frankfurt", "Milan",
    "Naples", "Florence", "Venice", "Seville", "Valencia", "Porto",
    "Cairo", "Nairobi", "Lagos", "Casablanca", "Johannesburg",
    "Beijing", "Shanghai", "Seoul", "Singapore", "Sydney", "Melbourne",
    "Toronto", "Montreal", "Vancouver", "Mexico City", "Lima", "Bogota",
]


def _extract_cities(prompt: str) -> list[str]:
    """Best-effort city extraction from a free-text prompt."""
    found = []
    for city in KNOWN_CITIES:
        if re.search(rf"\b{re.escape(city)}\b", prompt, re.IGNORECASE):
            found.append(city)
    return found if found else ["Paris", "Rome", "Athens", "Istanbul"]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/plan", methods=["POST"])
def plan():
    body = request.json or {}
    user_prompt = body.get("prompt", "").strip()
    mode = body.get("mode", "mcp")   # "mcp" or "no-mcp"

    if not user_prompt:
        return jsonify({"error": "Please enter a travel prompt."}), 400

    try:
        if mode == "mcp":
            result = run_journey_sync(user_prompt)
            result["mode"] = "mcp"
        else:
            cities = _extract_cities(user_prompt)
            result = run_without_mcp(cities)
            result["mode"] = "no-mcp"
            result["cities"] = cities
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Travel Journey MCP Planner running at http://localhost:5000")
    app.run(debug=False, port=5000)
