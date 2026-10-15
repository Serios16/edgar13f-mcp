#!/usr/bin/env bash
# Stage 5 (a): protocol check of the stdio server with the MCP Inspector CLI (pinned in
# tests/inspector/package.json), following the Inspector's "Smoke-testing an MCP server" guide:
# --method initialize / tools/list / tools/call, --format json, one CLI process per assertion,
# the "<target> -- <inspector options>" form, a bounded connect, an isolated token/secret store.
#
#   bash tests/inspector/inspector_check.sh OUT.json PYTHON [MODULE]
#
# MODULE defaults to edgar13f.server; tests.inspector.three_tools_server is the planted failure.
# The server runs on recorded fixtures (EDGAR13F_FIXTURE_DIR) with SEC_USER_AGENT unset, so nothing
# reaches sec.gov; its cache dir must stay without a requests.log. Assertions, in each protocol era
# (legacy = initialize handshake, modern = 2026-07-28): the connection succeeds; exactly the four
# tools are listed; one call per tool returns the disclaimer (structuredContent and first text
# block); a malformed call returns the invalid_argument decline (isError false). OUT.json gets a
# summary without any holdings row (protocol version, tool names, statuses).
set -euo pipefail

out="$1"; py="$2"; module="${3:-edgar13f.server}"
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
inspector="$here/node_modules/.bin/mcp-inspector"
unset SEC_USER_AGENT EDGAR13F_REDACT EDGAR13F_AGENT_MODE MCP_CATALOG_PATH
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
export MCP_STORAGE_DIR="$work/inspector"
export MCP_INSPECTOR_OAUTH_STATE_PATH="$MCP_STORAGE_DIR/oauth.json"
export MCP_INSPECTOR_SECRET_STORE=memory
cache="$work/cache"
disclaimer="$(cd "$repo" && "$py" -c 'from edgar13f import DISCLAIMER; print(DISCLAIMER)')"
fail() { echo "FAIL: $*" >&2; exit 1; }

mcp() {  # mcp ERA ARGS...: one Inspector CLI run; stdout = the JSON envelope
  local era="$1"; shift
  (cd "$repo" && "$inspector" --cli "$py" -m "$module" -- \
     -e "EDGAR13F_FIXTURE_DIR=$repo/tests/fixtures" -e "EDGAR13F_CACHE_DIR=$cache" \
     -e "PYTHONPATH=$repo" --protocol-era "$era" --connect-timeout 20000 --format json "$@")
}

call() {  # call ERA TOOL ARGS_JSON -> prints {exit, isError, status, reason, disclaimer_ok}
  local era="$1" tool="$2" args="$3" status=0 res
  res="$(mcp "$era" --method tools/call --tool-name "$tool" --tool-args-json "$args")" || status=$?
  jq -c --arg d "$disclaimer" --argjson exit "$status" '.result as $r
    | ($r.content[0].text | fromjson) as $t
    | {exit: $exit, isError: $r.isError, status: $r.structuredContent.status,
       reason: $r.structuredContent.reason,
       disclaimer_ok: ($r.structuredContent.disclaimer == $d and $t.disclaimer == $d and $t == $r.structuredContent)}' \
    <<<"$res" || fail "$era: $tool returned no parsable result (exit $status)"
}

want='["diff_holdings","find_manager","get_holdings_as_of","list_13f_filings"]'
summary='{}'
for era in legacy modern; do
  status=0
  init="$(mcp "$era" --method initialize)" || status=$?
  [ "$status" -eq 0 ] || fail "$era: connection failed (Inspector exit $status)"
  version="$(jq -r '.result.protocolVersion' <<<"$init")"
  [ -n "$version" ] && [ "$version" != null ] || fail "$era: no protocolVersion"
  echo "ok: $era: connected, protocolVersion $version"

  listed="$(mcp "$era" --method tools/list)" || fail "$era: tools/list failed"
  names="$(jq -c '[.result.tools[].name] | sort' <<<"$listed")"
  [ "$names" = "$want" ] || fail "$era: tools/list returned $names, expected exactly $want"
  echo "ok: $era: exactly the four tools"

  calls='{}'
  for spec in \
    'list_13f_filings|{"cik":"1067983","as_of":"2025-08-14"}' \
    'get_holdings_as_of|{"cik":"1067983","period":"2025-03-31","as_of":"2025-08-14","max_positions":5}' \
    'diff_holdings|{"cik":"1067983","period_a":"2024-12-31","period_b":"2025-03-31","as_of":"2025-08-14","cusip":["037833100"]}' \
    'find_manager|{"name":"berkshire","as_of":"2025-08-14"}'; do
    tool="${spec%%|*}"
    got="$(call "$era" "$tool" "${spec#*|}")"
    jq -e '.exit == 0 and .isError == false and .status == "ok" and .disclaimer_ok' <<<"$got" >/dev/null \
      || fail "$era: $tool: $got"
    calls="$(jq -c --arg t "$tool" --argjson g "$got" '. + {($t): $g}' <<<"$calls")"
  done
  echo "ok: $era: one call per tool, each with the disclaimer"

  bad="$(call "$era" get_holdings_as_of '{"cik":1067983,"period":"2025-03-31","as_of":"2025-08-14"}')"
  jq -e '.exit == 0 and .isError == false and .status == "declined" and .reason == "invalid_argument" and .disclaimer_ok' \
    <<<"$bad" >/dev/null || fail "$era: malformed call: $bad"
  echo "ok: $era: malformed call -> invalid_argument decline"

  summary="$(jq -c --arg era "$era" --arg v "$version" --argjson init "$init" --argjson names "$names" \
    --argjson calls "$calls" --argjson bad "$bad" \
    '. + {($era): {protocolVersion: $v, serverInfo: $init.result.serverInfo, tools: $names,
                   calls: $calls, malformed_call: $bad}}' <<<"$summary")"
done

[ ! -e "$cache/requests.log" ] || fail "the server logged SEC requests"
echo "ok: no request to sec.gov was attempted (no requests.log in the cache dir)"
inspector_version="$(jq -r .version "$here/node_modules/@modelcontextprotocol/inspector/package.json")"
jq -S --arg iv "$inspector_version" '{inspector: ("@modelcontextprotocol/inspector@" + $iv), eras: .,
  sec_requests_logged: false}' <<<"$summary" > "$out"
echo "inspector check OK ($out)"
