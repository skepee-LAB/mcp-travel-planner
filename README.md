# MCP Travel Journey Planner

> A practical, working demonstration of the **Model Context Protocol (MCP)** applied to a real-world use case: AI-powered travel journey planning using multiple live public APIs.

---

## Table of Contents

- [What is MCP?](#what-is-mcp)
- [Why MCP? The Core Problem It Solves](#why-mcp-the-core-problem-it-solves)
- [Architecture: With vs Without MCP](#architecture-with-vs-without-mcp)
- [Technical Deep Dive](#technical-deep-dive)
  - [The MCP Protocol Layer](#the-mcp-protocol-layer)
  - [Tool Discovery](#tool-discovery)
  - [The Agentic Loop](#the-agentic-loop)
- [This Project](#this-project)
  - [Data Sources (all free, no API key)](#data-sources-all-free-no-api-key)
  - [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Key Takeaways](#key-takeaways)

---

## What is MCP?

The **Model Context Protocol (MCP)** is an open standard, introduced by Anthropic in late 2024, that defines how AI language models connect to external data sources and tools. It is to AI integrations what REST is to web APIs — a universal contract that decouples producers of data (MCP Servers) from consumers of data (MCP Clients, i.e. LLM-powered apps).

MCP is transport-agnostic (supports `stdio`, HTTP/SSE, WebSocket) and language-agnostic, with official SDKs in Python and TypeScript.

**Official spec:** https://modelcontextprotocol.io

---

## Why MCP? The Core Problem It Solves

### The Integration Hell Problem

Before MCP, every AI application had to build its own custom integration for every data source:

```
App A ──── custom glue code ──── Database
App A ──── custom glue code ──── Weather API
App A ──── custom glue code ──── Wikipedia

App B ──── custom glue code ──── Database        ← duplicated!
App B ──── custom glue code ──── Weather API     ← duplicated!
App B ──── custom glue code ──── Wikipedia       ← duplicated!
```

This is the **M × N integration problem**: M applications × N data sources = M×N custom integrations to build and maintain.

### The MCP Solution

MCP introduces a standard server layer that any client can connect to:

```
App A ──┐
App B ──┼──── MCP Client ──── MCP Server ──── Database
App C ──┘                                 └── Weather API
                                          └── Wikipedia
```

Now it's **M + N**: M clients connect to N servers using one shared protocol.

---

## Architecture: With vs Without MCP

### ❌ Without MCP (`without_mcp.py`)

```
Developer writes:
  ┌─────────────────────────────────────────────┐
  │  for each city:                             │
  │    coords  = call_geocoding_api(city)       │
  │    weather = call_weather_api(coords)       │
  │    info    = call_wikipedia_api(city)       │
  │    fx      = call_currency_api(city)        │
  │                                             │
  │  context = dump_all_to_json(all_data)       │
  │  prompt  = f"Here is ALL data:\n{context}" │
  │  answer  = llm.complete(prompt)             │
  └─────────────────────────────────────────────┘
```

**Problems:**
| Issue | Impact |
|---|---|
| All data fetched upfront, blindly | Token waste — LLM receives data it may not need |
| Developer decides what to fetch | Rigid — LLM cannot ask for more data on demand |
| No reusability | Every new app duplicates the same HTTP calls |
| Tight coupling | Changing an API breaks the whole app |
| No tool composability | Cannot mix-and-match data sources easily |

---

### ✅ With MCP (`mcp_server.py` + `mcp_core.py`)

```
┌─────────────────────────┐         ┌──────────────────────────────────┐
│       MCP CLIENT        │         │          MCP SERVER              │
│  (mcp_core.py + Gemini) │         │        (mcp_server.py)           │
│                         │  stdio  │                                  │
│  1. Connect & discover  │────────▶│  Exposes tools:                  │
│     available tools     │◀────────│    • get_coordinates(city)       │
│                         │         │    • get_weather(city)           │
│  2. Send user prompt    │         │    • get_place_info(city)        │
│     to Gemini with      │         │    • get_currency_rate(from, to) │
│     tool definitions    │         │                                  │
│                         │         │  Each tool:                      │
│  3. Gemini decides      │         │    - calls real public APIs      │
│     which tool to call  │         │    - returns structured JSON     │
│     and with what args  │         │    - is independently testable   │
│                         │  stdio  │                                  │
│  4. Client calls tool   │────────▶│  Executes tool, calls APIs       │
│     on MCP server       │◀────────│  Returns result                  │
│                         │         │                                  │
│  5. Result fed back     │         └──────────────────────────────────┘
│     to Gemini           │
│                         │
│  6. Repeat until        │
│     Gemini has enough   │
│     → final answer      │
└─────────────────────────┘
```

---

## Technical Deep Dive

### The MCP Protocol Layer

MCP uses **JSON-RPC 2.0** over a chosen transport. In this project we use `stdio` (standard input/output), meaning the client spawns the server as a subprocess and communicates via pipes. This is the simplest and most portable transport.

A typical session looks like:

```
Client → Server:  {"jsonrpc":"2.0","method":"initialize","params":{...},"id":1}
Server → Client:  {"jsonrpc":"2.0","result":{"capabilities":{...}},"id":1}

Client → Server:  {"jsonrpc":"2.0","method":"tools/list","id":2}
Server → Client:  {"jsonrpc":"2.0","result":{"tools":[
                    {"name":"get_weather","description":"...","inputSchema":{...}},
                    ...
                  ]},"id":2}

Client → Server:  {"jsonrpc":"2.0","method":"tools/call",
                   "params":{"name":"get_weather","arguments":{"city":"Paris"}},"id":3}
Server → Client:  {"jsonrpc":"2.0","result":{"content":[{"type":"text","text":"{...}"}]},"id":3}
```

This is fully handled by the `mcp` Python SDK — you never write raw JSON-RPC.

---

### Tool Discovery

One of MCP's most powerful features is **automatic tool discovery**. The client does not need to know in advance what tools exist:

```python
# Client discovers tools at runtime — zero hardcoding
tools_response = await session.list_tools()
available_tools = tools_response.tools
# → [get_coordinates, get_weather, get_place_info, get_currency_rate]

# Converts MCP tool schema to LLM-native format automatically
gemini_tools = [
    types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name=t.name,
            description=t.description,
            parameters=t.inputSchema,   # ← JSON Schema, directly usable by Gemini
        )
        for t in available_tools
    ])
]
```

Add a new tool to `mcp_server.py`? The client picks it up automatically on the next request — **no client code changes needed**.

---

### The Agentic Loop

The LLM drives the entire data-fetching process autonomously:

```python
while True:
    # 1. LLM reasons about what it still needs
    response = gemini.generate_content(contents, tools=gemini_tools)

    # 2. If no tool calls → LLM has everything it needs → done
    if no_function_calls(response):
        return response.text

    # 3. Otherwise, execute the requested tool calls
    for fc in response.function_calls:
        result = await mcp_session.call_tool(fc.name, fc.args)
        # Feed result back into conversation
        contents.append(tool_result(fc.name, result))

    # 4. Loop — LLM may call more tools based on what it just learned
```

This means the LLM can:
- Call tools **conditionally** (e.g., only get currency if the country uses a non-EUR currency)
- Call tools **sequentially** (e.g., geocode first, then use coordinates for weather)
- Call tools **in parallel** (when the LLM groups multiple tool calls in one response)
- **Decide not to call** a tool if it already has enough information

---

### Tool Definition Example

Defining a tool on the MCP server is as simple as decorating a Python function:

```python
# mcp_server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Travel Journey Server")

@mcp.tool()
def get_weather(city: str) -> dict:
    """
    Get current weather and 3-day forecast for a city.
    The docstring becomes the tool description that Gemini uses to decide when to call it.
    """
    geo = _geocode(city)
    # ... call Open-Meteo API ...
    return {"city": ..., "current": {...}, "forecast_3_days": [...]}

mcp.run(transport="stdio")
```

The `@mcp.tool()` decorator:
- Extracts the function signature to build the **JSON Schema** (`inputSchema`)
- Uses the **docstring** as the tool description for the LLM
- Handles serialization/deserialization automatically

---

## This Project

### Data Sources (all free, no API key)

| Tool | API | What it provides |
|---|---|---|
| `get_coordinates` | [Open-Meteo Geocoding](https://geocoding-api.open-meteo.com) | lat/lon, timezone, country |
| `get_weather` | [Open-Meteo Forecast](https://open-meteo.com) | Current weather + 3-day forecast |
| `get_place_info` | [Wikipedia REST API](https://en.wikipedia.org/api/rest_v1/) | City summary and description |
| `get_currency_rate` | [Frankfurter.app](https://www.frankfurter.app) | Live FX rates between any two currencies |

### Project Structure

```
MCP/
│
├── mcp_server.py       # MCP Server — exposes 4 travel tools
│                       # Each tool = one @mcp.tool() decorated function
│                       # Runs as a stdio subprocess
│
├── mcp_core.py         # Core async MCP client logic
│                       # Connects to server, runs the Gemini agentic loop
│                       # Model fallback chain: gemini-2.5-flash → 2.0-flash → 2.0-flash-lite
│
├── app.py              # Flask web server
│                       # Single route: POST /plan → calls mcp_core → returns JSON
│
├── templates/
│   └── index.html      # Single-page web UI
│                       # Shows live tool calls + renders answer as Markdown
│
├── without_mcp.py      # ⚡ Comparison script — same task WITHOUT MCP
│                       # Manually fetches all data, dumps into prompt
│
├── mcp_client.py       # CLI version of the MCP client (for terminal use)
│
├── requirements.txt    # mcp[cli], httpx, google-genai, flask, python-dotenv
├── .env.example        # Template — copy to .env and add GEMINI_API_KEY
└── .gitignore
```

---

## Getting Started

### 1. Clone and install

```bash
git clone https://github.com/skepee-LAB/mcp-travel-planner
cd mcp-travel-planner
pip install -r requirements.txt
```

### 2. Set up your free Gemini API key

```bash
cp .env.example .env
# Edit .env and set: GEMINI_API_KEY=your_key_here
```

Get a free key (no credit card) at: https://aistudio.google.com/app/apikey

### 3. Run the web app

```bash
# Windows
set PYTHONUTF8=1 && python app.py

# macOS/Linux
PYTHONUTF8=1 python app.py
```

Then open **http://localhost:5000**

### 4. Or run the CLI comparison

```bash
# Traditional approach (no MCP)
python without_mcp.py

# MCP approach
python mcp_client.py
```

---

## Key Takeaways

### What MCP Gives You

| | Without MCP | With MCP |
|---|---|---|
| **Who decides what to fetch** | Developer (hardcoded) | LLM (at runtime) |
| **Data fetched** | Everything, upfront, blindly | Only what's needed |
| **Token efficiency** | Low — full data dump in prompt | High — only relevant data fetched |
| **Reusability** | Zero — tied to one app | Full — any MCP client can connect |
| **Tool discovery** | None — developer must know all APIs | Automatic — client asks server |
| **Adding a new data source** | Edit every app that needs it | Add one `@mcp.tool()` to the server |
| **Separation of concerns** | None — logic mixed in app | Clean — server owns data, client owns conversation |
| **LLM autonomy** | None — LLM is passive | Full — LLM reasons about what it needs |

### When to Use MCP

MCP shines when:
- You have **multiple data sources** that an LLM needs to query
- **Different apps** need access to the same data (write once, use everywhere)
- The **set of tools may grow** over time without breaking existing clients
- You want the **LLM to decide** what to fetch rather than pre-fetching everything
- You want your tools to be usable from **VS Code Copilot, Claude Desktop**, or any other MCP host

### When Not to Use MCP

MCP adds overhead (subprocess spawning, JSON-RPC handshake). For a simple, single-purpose app with one fixed data source, a direct API call is simpler. MCP is the right choice when **reusability, composability, and LLM autonomy** matter.

---

## License

MIT
