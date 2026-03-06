"""
WITH MCP – LLM-driven travel journey planning
----------------------------------------------
Advantages this demonstrates:
  ✅ LLM DECIDES which tools to call and in what order
  ✅ LLM DECIDES which cities to look up (no hardcoding)
  ✅ Only fetches what's actually needed (efficient token use)
  ✅ Tools are reusable by ANY MCP client (VS Code Copilot, Gemini apps, etc.)
  ✅ Adding a new data source = add one tool to mcp_server.py, nothing else
  ✅ LLM can call tools multiple times or conditionally based on results
  ✅ Clean separation: server owns data logic, client owns conversation
"""

import asyncio
import json
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

JOURNEY_PROMPT = (
    "I'm planning a travel journey from Paris to Rome, then Athens, then Istanbul. "
    "For each city please: (1) get the current weather and 3-day forecast, "
    "(2) give me interesting place info, (3) tell me the local currency rate vs EUR. "
    "Finally summarize: overall weather across the trip, what to pack, and budget tips."
)

async def run_mcp_journey():
    # ── Connect to the MCP server via stdio ──────────────────────
    server_params = StdioServerParameters(
        command="python",
        args=["mcp_server.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
    )

    print("🚀 Starting MCP server and connecting...\n")

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ── Discover available tools automatically ────────────
            tools_response = await session.list_tools()
            available_tools = tools_response.tools

            print(f"🔧 MCP tools discovered: {[t.name for t in available_tools]}\n")

            # Convert MCP tools to Gemini function declarations
            gemini_tools = [
                types.Tool(function_declarations=[
                    types.FunctionDeclaration(
                        name=t.name,
                        description=t.description,
                        parameters=t.inputSchema,
                    )
                    for t in available_tools
                ])
            ]

            # ── Start conversation with Gemini ────────────────────
            gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            GEMINI_MODEL = "gemini-2.0-flash"

            print(f"👤 User: {JOURNEY_PROMPT}\n")
            print("─" * 60)

            tool_call_count = 0
            total_input_tokens = 0
            total_output_tokens = 0

            # Build conversation history in Gemini format
            contents = [types.Content(role="user", parts=[types.Part(text=JOURNEY_PROMPT)])]

            # ── Agentic loop: Gemini calls tools until it has enough ──
            while True:
                response = gemini_client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=contents,
                    config=types.GenerateContentConfig(tools=gemini_tools),
                )

                total_input_tokens += response.usage_metadata.prompt_token_count or 0
                total_output_tokens += response.usage_metadata.candidates_token_count or 0

                candidate = response.candidates[0]
                parts = candidate.content.parts

                # Check if there are any function calls in the response
                function_calls = [p for p in parts if p.function_call is not None]

                # ── No more tool calls → final answer ────────────
                if not function_calls:
                    print("\n✈️  TRAVEL PLAN (with MCP)\n")
                    for part in parts:
                        if part.text:
                            print(part.text)
                    break

                # Add model's response to history
                contents.append(types.Content(role="model", parts=parts))

                # ── Process tool calls requested by Gemini ────────
                tool_result_parts = []
                for part in function_calls:
                    fc = part.function_call
                    tool_call_count += 1
                    tool_name = fc.name
                    tool_input = dict(fc.args)

                    print(f"  🔧 [{tool_call_count}] Gemini calls: {tool_name}({json.dumps(tool_input)})")

                    # Call the tool on the MCP server
                    result = await session.call_tool(tool_name, tool_input)
                    result_text = result.content[0].text if result.content else "{}"

                    print(f"     ✅ Result preview: {result_text[:120]}...")

                    tool_result_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=tool_name,
                                response={"result": result_text},
                            )
                        )
                    )

                # Add tool results to conversation history
                contents.append(types.Content(role="user", parts=tool_result_parts))

            # ── Stats comparison ───────────────────────────────────
            print("\n" + "="*60)
            print(f"📊 MCP Stats:")
            print(f"   🔧 Tool calls made by Gemini: {tool_call_count}")
            print(f"   📥 Total input tokens:     {total_input_tokens:,}")
            print(f"   📤 Total output tokens:    {total_output_tokens:,}")
            print(f"   💡 LLM fetched only what it needed — no wasted data!")
            print("="*60)

if __name__ == "__main__":
    asyncio.run(run_mcp_journey())
