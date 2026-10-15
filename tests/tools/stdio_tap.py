"""Record the JSON-RPC envelope of every stdio message between a client and a server (stage 5 (a)).

    python -m tests.tools.stdio_tap LOG.jsonl COMMAND...

Runs COMMAND with this process's stdin/stdout piped through; appends one line per message to LOG:
direction, method, id, the protocol version fields (`params.protocolVersion`, `result.protocolVersion`,
`result.supportedVersions`, the `params._meta` keys and its protocol version) and the top-level result/error keys. No payload is recorded.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading


def _summary(direction: str, line: bytes) -> dict:
    try:
        msg = json.loads(line)
    except ValueError:
        return {"dir": direction, "not_json": True}
    if not isinstance(msg, dict):
        return {"dir": direction, "type": type(msg).__name__}
    params, result = msg.get("params") or {}, msg.get("result")
    out = {"dir": direction, "method": msg.get("method"), "id": msg.get("id")}
    if isinstance(params, dict):
        out["params.protocolVersion"] = params.get("protocolVersion")
        meta = params.get("_meta") or {}
        out["params._meta"] = sorted(meta)
        out["params._meta.protocolVersion"] = meta.get("io.modelcontextprotocol/protocolVersion")
    if isinstance(result, dict):
        out["result.keys"] = sorted(result)
        out["result.protocolVersion"] = result.get("protocolVersion")
        out["result.supportedVersions"] = result.get("supportedVersions")
    if "error" in msg:
        out["error.code"] = (msg["error"] or {}).get("code")
    return {k: v for k, v in out.items() if v not in (None, [])}


def main() -> None:
    log, cmd = sys.argv[1], sys.argv[2:]
    child = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    lock = threading.Lock()

    def record(direction: str, line: bytes) -> None:
        with lock, open(log, "a") as fh:
            fh.write(json.dumps(_summary(direction, line)) + "\n")

    def pump_in() -> None:
        for line in sys.stdin.buffer:
            record("client->server", line)
            child.stdin.write(line)
            child.stdin.flush()
        child.stdin.close()

    threading.Thread(target=pump_in, daemon=True).start()
    for line in child.stdout:
        record("server->client", line)
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
    sys.exit(child.wait())


if __name__ == "__main__":
    main()
