"""MCP stdio server: `python -m edgar13f.server`.

Uses the low-level MCP Python SDK 2.x `Server` so that argument validation stays
ours: unknown or malformed arguments become `invalid_argument` declines
(isError=false) as CONTRACTS §2/§6 require, instead of SDK-level errors.
Set EDGAR13F_FIXTURE_DIR to serve recorded fixtures instead of live EDGAR; it is
refused together with EDGAR13F_REDACT=off.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio
import mcp_types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from . import __version__, blocklist, config, tools
from .schemas import TOOL_DEFS
from .sec_client import SecClient
from .sources import EdgarSource, FixtureSource


def make_source():
    fixtures = os.environ.get("EDGAR13F_FIXTURE_DIR")
    if fixtures:
        if not blocklist.redacting():
            sys.exit("edgar13f: EDGAR13F_REDACT=off is not allowed with EDGAR13F_FIXTURE_DIR")
        return FixtureSource(Path(fixtures))
    cache = config.cache_dir()
    return EdgarSource(SecClient(cache, config.user_agent()), cache)


def result_for(source, name: str, arguments: dict | None) -> types.CallToolResult:
    if name not in tools.TOOLS:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"unknown tool: {name}")], is_error=True
        )
    try:
        obj = tools.call(source, name, arguments)
    except Exception as exc:  # transport/internal failure: isError=true (CONTRACTS §5.1)
        print(f"edgar13f: {name} failed: {exc!r}", file=sys.stderr)
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=f"internal error: {type(exc).__name__}: {exc}")],
            is_error=True,
        )
    text = json.dumps(obj, ensure_ascii=False)
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], structured_content=obj, is_error=False
    )


def build_server(source) -> Server:
    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[
            types.Tool(name=name, description=d["description"], input_schema=d["inputSchema"])
            for name, d in TOOL_DEFS.items()
        ])

    async def on_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        return await anyio.to_thread.run_sync(result_for, source, params.name, params.arguments)

    return Server("edgar13f", version=__version__, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def _serve() -> None:
    server = build_server(make_source())
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    anyio.run(_serve)


if __name__ == "__main__":
    main()
