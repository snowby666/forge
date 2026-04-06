#!/usr/bin/env python3
"""Quick smoke-test for the Google Stitch MCP integration.

Usage:
    python scripts/test_stitch.py

Requires STITCH_API_KEY in .env (get one at https://stitch.withgoogle.com/settings).
Also requires: pip install mcp
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(encoding="utf-8-sig")

STITCH_MCP_URL = "https://stitch.googleapis.com/mcp"


def _get_api_key() -> str:
    return (
        os.environ.get("STITCH_API_KEY")
        or os.environ.get("GOOGLE_STITCH_TOKENS", "").split(",")[0].strip()
    )


async def test_mcp_connection():
    """Test raw MCP connection to Stitch."""
    api_key = _get_api_key()
    if not api_key:
        print("SKIP: STITCH_API_KEY not set")
        print("      Get one at: https://stitch.withgoogle.com/settings")
        return False

    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        import httpx
    except ImportError:
        print("FAIL: `mcp` package not installed — pip install mcp")
        return False

    print(f"Connecting to {STITCH_MCP_URL} ...")
    print(f"Key: {api_key[:8]}...{api_key[-4:]}")

    http = httpx.AsyncClient(
        headers={"x-goog-api-key": api_key},
        timeout=httpx.Timeout(60.0, connect=15.0),
    )

    try:
        async with streamable_http_client(STITCH_MCP_URL, http_client=http) as (
            read_stream,
            write_stream,
            _get_sid,
        ):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("OK: MCP session initialized")

                tools = await session.list_tools()
                tool_names = [t.name for t in tools.tools]
                print(f"OK: {len(tool_names)} tools: {tool_names}")

                # Verify auth works for actual tool calls (not just list_tools which is public)
                print("Testing auth with list_projects...")
                result = await session.call_tool("list_projects", {})
                if result.isError:
                    print(f"FAIL: Auth rejected — {result.content}")
                    print("      Your key may be invalid. Get a fresh one at:")
                    print("      https://stitch.withgoogle.com/settings")
                    return False

                projects = []
                for block in result.content:
                    if hasattr(block, "text"):
                        projects = json.loads(block.text) if block.text.startswith("[") else [json.loads(block.text)]
                print(f"OK: Auth verified — {len(projects)} existing project(s)")
                return True

    except ExceptionGroup as eg:
        for exc in eg.exceptions:
            if "401" in str(exc):
                print("FAIL: 401 Unauthorized — your API key is invalid for tool calls.")
                print("      Get a valid key at: https://stitch.withgoogle.com/settings")
                print(f"      (initialize/list_tools are public, call_tool requires auth)")
                return False
            raise
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return False


async def test_generate_screen():
    """Test the full flow: create project → generate screen."""
    api_key = _get_api_key()

    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    import httpx

    http = httpx.AsyncClient(
        headers={"x-goog-api-key": api_key},
        timeout=httpx.Timeout(300.0, connect=15.0),
    )

    async with streamable_http_client(STITCH_MCP_URL, http_client=http) as (
        read_stream,
        write_stream,
        _get_sid,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Create project
            print("Creating test project...")
            result = await session.call_tool("create_project", {"title": f"forge-test-{os.getpid()}"})
            if result.isError:
                print(f"FAIL: create_project error: {result.content}")
                return
            project_id = ""
            for block in result.content:
                if hasattr(block, "text"):
                    data = json.loads(block.text)
                    project_id = str(data.get("projectId") or data.get("id", ""))
            print(f"OK: Project created: {project_id}")

            # Generate screen (1-3 min)
            prompt = (
                "A dark-themed dashboard for a hackathon project tracker with a sidebar, "
                "status cards showing team progress, and a timeline of milestones"
            )
            print(f"Generating screen (this takes 1-3 min)...")
            result = await session.call_tool(
                "generate_screen_from_text",
                {"projectId": project_id, "prompt": prompt, "deviceType": "DESKTOP"},
            )
            if result.isError:
                print(f"FAIL: generate_screen error: {result.content}")
                return

            for block in result.content:
                if hasattr(block, "text"):
                    data = json.loads(block.text)
                    screen_id = data.get("screenId") or data.get("id", "")
                    html_url = data.get("htmlCode", {}).get("downloadUrl", "N/A")
                    img_url = data.get("screenshot", {}).get("downloadUrl", "N/A")
                    print(f"OK: Screen generated: {screen_id}")
                    print(f"    HTML: {html_url[:120]}")
                    print(f"    Image: {img_url[:120]}")


async def main():
    print("=" * 60)
    print("Google Stitch MCP Integration Test")
    print("=" * 60)

    print("\n--- Test 1: MCP Connection + Auth ---")
    ok = await test_mcp_connection()
    if not ok:
        print("\nStopping — fix auth first.")
        return

    print("\n--- Test 2: Create Project + Generate Screen ---")
    await test_generate_screen()

    print("\n" + "=" * 60)
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
