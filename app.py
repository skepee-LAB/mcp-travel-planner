"""
Flask web interface for the MCP Travel Journey Planner.
Run with: python app.py
Then open: http://localhost:5000
"""

import os
from flask import Flask, render_template, request, jsonify
from mcp_core import run_journey_sync

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/plan", methods=["POST"])
def plan():
    user_prompt = request.json.get("prompt", "").strip()
    if not user_prompt:
        return jsonify({"error": "Please enter a travel prompt."}), 400

    try:
        result = run_journey_sync(user_prompt)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    print("Travel Journey MCP Planner running at http://localhost:5000")
    app.run(debug=False, port=5000)
