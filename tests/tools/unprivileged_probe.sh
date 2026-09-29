#!/usr/bin/env bash
# Run the server as a separate unprivileged user that can read (not write) only a
# copy of this checkout, then list every file that user created anywhere.
# Needs root, network (PyPI + sec.gov) and SEC_USER_AGENT. Not run in CI.
set -euo pipefail
SRC=$(cd "$(dirname "$0")/../.." && pwd)
PROBE_USER=edgar13f-probe
CO=/srv/edgar13f-checkout
id "$PROBE_USER" >/dev/null 2>&1 || useradd --create-home --shell /usr/sbin/nologin "$PROBE_USER"
rm -rf "$CO" && mkdir -p "$CO"
git -C "$SRC" archive HEAD | tar -x -C "$CO"
python3.11 -m venv "$CO/.venv" && "$CO/.venv/bin/pip" install -q "$CO" >/dev/null
chown -R root:root "$CO" && chmod -R a+rX,go-w "$CO"
PUID=$(id -u "$PROBE_USER")
rm -rf "/home/$PROBE_USER/explicit-cache" "/home/$PROBE_USER/.cache/edgar13f" "/tmp/edgar13f-$PUID"  # start cold
QUERY='{"cik":"1993399","as_of":"2025-03-01"}'
run() {  # $1 = label, rest = env assignments
  local label=$1; shift
  touch /tmp/.edgar13f-marker; sleep 1
  echo "== $label"
  sudo -u "$PROBE_USER" env -i PATH=/usr/bin:/bin SEC_USER_AGENT="$SEC_USER_AGENT" \
    HTTPS_PROXY="${HTTPS_PROXY:-}" SSL_CERT_FILE="${SSL_CERT_FILE:-}" "$@" \
    "$CO/.venv/bin/python" - "$QUERY" <<'PY'
import json, sys, anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import os
async def main():
    p = StdioServerParameters(command=sys.executable, args=["-m", "edgar13f.server"], env=dict(os.environ))
    async with stdio_client(p) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("list_13f_filings", json.loads(sys.argv[1]))
            body = json.loads(res.content[0].text)
            print("isError", res.is_error, "status", body["status"], "filings", len(body.get("filings", [])))
anyio.run(main)
PY
  echo "files created by $PROBE_USER since start:"
  find / -xdev \( -path /proc -o -path /sys \) -prune -o -user "$PROBE_USER" -newer /tmp/.edgar13f-marker -type f -print 2>/dev/null | sed 's/[0-9a-f]\{64\}$/<sha256>/' | sort | uniq -c
}
run "EDGAR13F_CACHE_DIR set" HOME=/home/$PROBE_USER EDGAR13F_CACHE_DIR=/home/$PROBE_USER/explicit-cache
run "unset, HOME writable" HOME=/home/$PROBE_USER
run "unset, HOME unwritable" HOME=/nonexistent
echo "== write attempt into checkout"
sudo -u "$PROBE_USER" touch "$CO/should-fail" 2>&1 || echo "denied as expected"
