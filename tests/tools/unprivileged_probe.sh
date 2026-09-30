#!/usr/bin/env bash
# Run the server as a separate unprivileged user that can read (not write) only a
# copy of this checkout, then list every file and directory that user created
# anywhere, and FAIL unless all of them are the expected cache dir (or its parents).
#
#   sudo env PYTHON=python3.11 bash tests/tools/unprivileged_probe.sh --offline   # CI
#   sudo -E bash tests/tools/unprivileged_probe.sh                                # live
#
# --offline (the CI step): no sec.gov, SEC_USER_AGENT unset. The server must answer
#   a malformed call with an invalid_argument decline (isError=false) and a live call
#   with isError=true (REGISTER A8). Needs root and the package index only.
# live: needs network (PyPI + sec.gov) and SEC_USER_AGENT; the live call must succeed.
set -euo pipefail
MODE=live
[ "${1:-}" = "--offline" ] && MODE=offline
PY=${PYTHON:-python3.11}
SRC=$(cd "$(dirname "$0")/../.." && pwd)
PROBE_USER=edgar13f-probe
CO=/srv/edgar13f-checkout
UA=${SEC_USER_AGENT:-}
[ "$MODE" = offline ] && UA=""
id "$PROBE_USER" >/dev/null 2>&1 || useradd --create-home --shell /usr/sbin/nologin "$PROBE_USER"
rm -rf "$CO" && mkdir -p "$CO"
git -c safe.directory='*' -C "$SRC" archive HEAD | tar -x -C "$CO"
"$PY" -m venv "$CO/.venv" && "$CO/.venv/bin/pip" install -q "$CO" >/dev/null
chown -R root:root "$CO" && chmod -R a+rX,go-w "$CO"
PUID=$(id -u "$PROBE_USER")
PHOME=/home/$PROBE_USER
rm -rf "$PHOME/explicit-cache" "$PHOME/.cache" "/tmp/edgar13f-$PUID"  # start cold
FAIL=0
fail() { echo "PROBE FAIL: $*"; FAIL=1; }

run() {  # $1 = label, $2 = expected cache dir, rest = env assignments
  local label=$1 expect=$2; shift 2
  touch /tmp/.edgar13f-marker; sleep 1
  echo "== $label (expect cache dir $expect)"
  local out
  out=$(sudo -u "$PROBE_USER" env -i PATH=/usr/bin:/bin SEC_USER_AGENT="$UA" \
    HTTPS_PROXY="${HTTPS_PROXY:-}" SSL_CERT_FILE="${SSL_CERT_FILE:-}" "$@" \
    "$CO/.venv/bin/python" - <<'PY'
import json, os, sys, anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
async def main():
    p = StdioServerParameters(command=sys.executable, args=["-m", "edgar13f.server"], env=dict(os.environ))
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            bad = await s.call_tool("list_13f_filings", {"cik": "x1", "as_of": "2025-03-01"})
            body = json.loads(bad.content[0].text)
            print("malformed: isError", bad.is_error, "reason", body.get("reason"))
            res = await s.call_tool("list_13f_filings", {"cik": "1993399", "as_of": "2025-03-01"})
            status = json.loads(res.content[0].text).get("status") if not res.is_error else "-"
            print("live: isError", res.is_error, "status", status)
anyio.run(main)
PY
  ) || fail "$label: client exited non-zero"
  echo "$out"
  grep -q "^malformed: isError False reason invalid_argument$" <<<"$out" || fail "$label: malformed call"
  if [ "$MODE" = offline ]; then
    grep -q "^live: isError True status -$" <<<"$out" || fail "$label: offline live call must be isError"
  else
    grep -q "^live: isError False status ok$" <<<"$out" || fail "$label: live call"
  fi
  echo "created by $PROBE_USER since start (files and dirs):"
  local created
  created=$(find / /run /dev/shm -xdev \( -path /proc -o -path /sys \) -prune -o \
    -user "$PROBE_USER" -newer /tmp/.edgar13f-marker -print 2>/dev/null | sort -u)
  sed 's/[0-9a-f]\{64\}$/<sha256>/' <<<"$created" | sort | uniq -c
  while IFS= read -r p; do
    [ -z "$p" ] && continue
    case "$p" in
      "$expect"|"$expect"/*) ;;
      *) case "$expect/" in "$p"/*) [ -d "$p" ] || fail "$label: unexpected file $p" ;;
                                *) fail "$label: write outside the cache dir: $p" ;; esac ;;
    esac
  done <<<"$created"
  [ -d "$expect" ] && [ "$(stat -c %U "$expect")" = "$PROBE_USER" ] || fail "$label: $expect not created"
  [ -d "$expect" ] && [ $(( 0$(stat -c %a "$expect") & 022 )) -eq 0 ] || fail "$label: $expect group/world-writable"
}
run "EDGAR13F_CACHE_DIR set" "$PHOME/explicit-cache" HOME="$PHOME" EDGAR13F_CACHE_DIR="$PHOME/explicit-cache"
run "unset, HOME writable" "$PHOME/.cache/edgar13f" HOME="$PHOME"
run "unset, HOME unwritable" "/tmp/edgar13f-$PUID" HOME=/nonexistent
echo "== write attempt into checkout"
if sudo -u "$PROBE_USER" touch "$CO/should-fail" 2>/dev/null; then fail "checkout is writable"; else echo "denied as expected"; fi
[ "$FAIL" = 0 ] && echo "PROBE OK ($MODE)" || { echo "PROBE FAILED ($MODE)"; exit 1; }
