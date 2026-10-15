#!/usr/bin/env bash
# Stage 5 (a): what goes over the wire in each protocol era. The Inspector CLI (pinned) runs
# initialize, tools/list and one tools/call through tests/tools/stdio_tap.py (envelopes only,
# no payload) against the fixture server; prints one JSON object per era with the tap lines.
#
#   bash tests/inspector/protocol_tap.sh PYTHON
set -euo pipefail
py="$1"
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
unset SEC_USER_AGENT EDGAR13F_REDACT EDGAR13F_AGENT_MODE MCP_CATALOG_PATH
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
export MCP_STORAGE_DIR="$work/inspector" MCP_INSPECTOR_OAUTH_STATE_PATH="$work/inspector/oauth.json"
export MCP_INSPECTOR_SECRET_STORE=memory
sdk="$(cd "$repo" && "$py" -c 'import importlib.metadata as m; print(m.version("mcp"))')"
for era in legacy modern; do
  for method in initialize tools/list tools/call; do
    (cd "$repo" && "$here/node_modules/.bin/mcp-inspector" --cli \
      "$py" -m tests.tools.stdio_tap "$work/$era.jsonl" "$py" -m edgar13f.server -- \
      -e "EDGAR13F_FIXTURE_DIR=$repo/tests/fixtures" -e "EDGAR13F_CACHE_DIR=$work/cache" -e "PYTHONPATH=$repo" \
      --protocol-era "$era" --connect-timeout 20000 --format json --method "$method" \
      ${method/tools\/call/--tool-name list_13f_filings --tool-args-json {\"cik\":\"1067983\",\"as_of\":\"2025-08-14\"}} \
      | jq -c --arg m "$method" '{method: $m, protocolVersion: .result.protocolVersion, isError: .result.isError}' >&2)
  done
  jq -cs --arg era "$era" --arg sdk "$sdk" '{sdk: ("mcp " + $sdk), era: $era, wire: .}' "$work/$era.jsonl"
done
