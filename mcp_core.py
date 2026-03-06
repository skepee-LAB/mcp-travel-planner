"""
Shared MCP journey logic – used by both app.py (web) and mcp_client.py (CLI).
Returns structured data so the caller can render it however it likes.
"""

import asyncio
import json
import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Try multiple models in order — falls back if one quota is exhausted
GEMINI_MODELS = [
    "models/gemini-2.5-flash",
    "models/gemini-2.0-flash",
    "models/gemini-2.0-flash-lite",
]


def _generate_with_retry(gemini_client, contents, config, max_retries=2):
    """Try each model in GEMINI_MODELS, with backoff on 429."""
    import re
    for model in GEMINI_MODELS:
        for attempt in range(max_retries):
            try:
                return gemini_client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=config,
                )
            except genai_errors.ClientError as e:
                msg = str(e)
                is_429 = '429' in msg or 'RESOURCE_EXHAUSTED' in msg
                is_quota_zero = 'limit: 0' in msg
                if is_429 and is_quota_zero:
                    # This model's daily quota is gone — try next model
                    print(f"Model {model} quota exhausted, trying next model...")
                    break
                elif is_429 and attempt < max_retries - 1:
                    # Parse retryDelay from error if available
                    delay_match = re.search(r'retry in (\d+)', msg)
                    wait = int(delay_match.group(1)) + 5 if delay_match else 30
                    print(f"Rate limited on {model}. Waiting {wait}s...")
                    time.sleep(wait)
                else:
                    raise
    raise RuntimeError(
        "All Gemini models quota exhausted for today. "
        "Please wait until midnight PT or add billing to your Google AI account at "
        "https://aistudio.google.com"
    )


async def run_journey(user_prompt: str, on_tool_call=None) -> dict:
    """
    Run the MCP travel journey with Gemini.

    Args:
        user_prompt:  The travel question from the user.
        on_tool_call: Optional async callback(tool_name, tool_input, result_text)
                      called each time Gemini invokes a tool.

    Returns:
        {
            "answer": str,          # final Gemini answer (markdown)
            "tool_calls": list,     # [{name, input, result_preview}]
            "input_tokens": int,
            "output_tokens": int,
        }
    """
    server_params = StdioServerParameters(
        command="python",
        args=["mcp_server.py"],
        cwd=BASE_DIR,
    )

    tool_log = []
    total_input = 0
    total_output = 0

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_response = await session.list_tools()
            available_tools = tools_response.tools

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

            gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            contents = [types.Content(role="user", parts=[types.Part(text=user_prompt)])]

            final_answer = ""

            while True:
                response = _generate_with_retry(
                    gemini_client,
                    contents,
                    types.GenerateContentConfig(tools=gemini_tools),
                )

                total_input += response.usage_metadata.prompt_token_count or 0
                total_output += response.usage_metadata.candidates_token_count or 0

                parts = response.candidates[0].content.parts
                function_calls = [p for p in parts if p.function_call is not None]

                if not function_calls:
                    final_answer = "\n".join(p.text for p in parts if p.text)
                    break

                contents.append(types.Content(role="model", parts=parts))

                tool_result_parts = []
                for part in function_calls:
                    fc = part.function_call
                    tool_name = fc.name
                    tool_input = dict(fc.args)

                    result = await session.call_tool(tool_name, tool_input)
                    result_text = result.content[0].text if result.content else "{}"

                    entry = {
                        "name": tool_name,
                        "input": tool_input,
                        "result_preview": result_text[:200],
                    }
                    tool_log.append(entry)

                    if on_tool_call:
                        await on_tool_call(tool_name, tool_input, result_text)

                    tool_result_parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=tool_name,
                                response={"result": result_text},
                            )
                        )
                    )

                contents.append(types.Content(role="user", parts=tool_result_parts))

    return {
        "answer": final_answer,
        "tool_calls": tool_log,
        "input_tokens": total_input,
        "output_tokens": total_output,
    }


def run_journey_sync(user_prompt: str) -> dict:
    """Synchronous wrapper for use in Flask."""
    return asyncio.run(run_journey(user_prompt))
