#!/usr/bin/env bash
# One-command install and run from GitHub, then an MCP stdio handshake (NOT run in CI;
# needs uv and network access to github.com and the package index).
#
#   PYTHON=.venv/bin/python bash tests/tools/install_smoke.sh [git ref]
#
# Runs the README command `uvx --python 3.11 --from git+https://github.com/Serios16/edgar13f-mcp[@REF] edgar13f-server`
# with an empty uv cache, so the package and its dependencies are fetched from scratch.
# SEC_USER_AGENT is unset, so the server never contacts sec.gov: a malformed call must be an
# invalid_argument decline and a well-formed call must be isError (REGISTER A8).
# $PYTHON must have the MCP SDK (the test client) installed.
set -euo pipefail
REF="${1:-}"
SOURCE="git+https://github.com/Serios16/edgar13f-mcp${REF:+@$REF}"
PY="${PYTHON:-python3}"
UV_CACHE_DIR="$(mktemp -d)"
CACHE="$(mktemp -d)"
trap 'rm -rf "$UV_CACHE_DIR" "$CACHE"' EXIT
echo "command: uvx --python 3.11 --from $SOURCE edgar13f-server"
echo "uv: $(uv --version)"
start=$(date +%s)
SOURCE="$SOURCE" UV_CACHE_DIR="$UV_CACHE_DIR" CACHE="$CACHE" "$PY" - <<'PY'
import json, os, sys
import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

env = {k: v for k, v in os.environ.items() if not k.startswith(("SEC_USER_AGENT", "EDGAR13F_"))}
env["EDGAR13F_CACHE_DIR"] = os.environ["CACHE"]
params = StdioServerParameters(command="uvx", args=["--python", "3.11", "--from", os.environ["SOURCE"], "edgar13f-server"],
                                env=env)


async def main():
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            init = await s.initialize()
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            bad = await s.call_tool("get_holdings_as_of", {"cik": "x", "period": "2025-03-31", "as_of": "2025-08-27"})
            live = await s.call_tool("list_13f_filings", {"cik": "1", "as_of": "2025-08-27"})
    body = json.loads(bad.content[0].text)
    print(f"server: {init.server_info.name} {init.server_info.version}")
    print(f"tools: {tools}")
    print(f"malformed call: isError={bad.is_error} status={body['status']} reason={body['reason']}")
    print(f"call without SEC_USER_AGENT: isError={live.is_error}")
    ok = (tools == ["diff_holdings", "get_holdings_as_of", "list_13f_filings"] and bad.is_error is False
          and body["reason"] == "invalid_argument" and live.is_error is True)
    print("SMOKE OK" if ok else "SMOKE FAIL")
    sys.exit(0 if ok else 1)

anyio.run(main)
PY
echo "elapsed (install + run, empty uv cache): $(( $(date +%s) - start )) s"
