"""End-to-end over MCP stdio: spawn `python -m edgar13f.server` on fixtures."""

from __future__ import annotations

import json
import sys

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from edgar13f import DISCLAIMER
from tests.conftest import FIXTURES

CALLS = [
    ("list_13f_filings", {"cik": "1067983", "as_of": "2025-08-14"}, "ok"),
    ("get_holdings_as_of", {"cik": "1067983", "period": "2025-03-31", "as_of": "2025-08-14"}, "ok"),
    ("diff_holdings", {"cik": "1067983", "period_a": "2024-12-31", "period_b": "2025-03-31",
                       "as_of": "2025-08-14", "cusip": ["037833100"]}, "ok"),
    ("get_holdings_as_of", {"cik": "1067983", "period": "2025-03-31", "as_of": "2025-08-14", "x": 1},
     "invalid_argument"),
    ("get_holdings_as_of", {"cik": "1450709", "period": "2024-09-30", "as_of": "2025-01-01"}, "notice_only"),
    ("list_13f_filings", {"cik": "999999999", "as_of": "2025-01-01"}, "unknown_cik"),
]


async def _session_run(tmp_path):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "edgar13f.server"],
        env={"EDGAR13F_FIXTURE_DIR": str(FIXTURES), "EDGAR13F_CACHE_DIR": str(tmp_path / "cache")},
    )
    out = {}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            out["tools"] = {t.name: t.input_schema for t in listed.tools}
            out["results"] = [await session.call_tool(name, args) for name, args, _ in CALLS]
            out["unknown_tool"] = await session.call_tool("nope", {})
    return out


def test_stdio_end_to_end(tmp_path):
    out = anyio.run(_session_run, tmp_path)
    assert set(out["tools"]) == {"list_13f_filings", "get_holdings_as_of", "diff_holdings"}
    assert out["tools"]["get_holdings_as_of"]["additionalProperties"] is False
    for (name, args, expected), res in zip(CALLS, out["results"]):
        assert res.is_error is False
        first = res.content[0]
        assert first.type == "text"
        body = json.loads(first.text)
        assert body["disclaimer"] == DISCLAIMER
        assert res.structured_content == body
        assert (body.get("reason") or body["status"]) == expected, (name, body.get("message"))
    assert out["unknown_tool"].is_error is True
