"""Stage 5 (b): observations behind tests/invariants/test_lifecycle.py, as JSON (offline).

    python -m tests.tools.lifecycle_observe > reports/artifacts/lifecycle_stage5.json

stdin close: seconds to exit and exit code (fixture server, offline EdgarSource server); malformed
lines: what came back for each; SIGTERM/SIGKILL mid-call: the client's error class and seconds from
the signal, the cache check and the fresh start; and the result of each planted control.
"""

from __future__ import annotations

import importlib.metadata
import json
import signal
import subprocess
import tempfile
import time
from pathlib import Path

from tests.invariants import test_lifecycle as tl


def stdin_close(cmd, env) -> dict:
    raw = tl.Raw(cmd, env)
    try:
        raw.handshake()
        tl._answers(raw)
        start = time.monotonic()
        raw.proc.stdin.close()
        try:
            code = raw.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            code = "still running after 10 s"
        return {"exit_code": code, "seconds": round(time.monotonic() - start, 3)}
    finally:
        raw.close()


def malformed(cmd, env) -> list[dict]:
    raw = tl.Raw(cmd, env)
    out = []
    try:
        raw.handshake()
        for bad in tl.BAD_LINES:
            raw.send(bad)
            replies = [line.decode(errors="replace").strip()[:160] for line in raw.lines(1.0)]
            out.append({"line": bad.decode(errors="replace"), "replies": replies,
                        "then_answers_correctly": tl._answers(raw) == []})
    finally:
        raw.close()
    return out


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        offline = {k: v for k, v in tl._env(t / "c2").items() if k != "EDGAR13F_FIXTURE_DIR"}
        result = {
            "mcp_sdk": importlib.metadata.version("mcp"),
            "stdin_close": {"fixture_server": stdin_close(tl.SERVER, tl._env(t / "c1")),
                            "offline_edgar_server": stdin_close(tl.OFFLINE, offline)},
            "malformed_lines": malformed(tl.SERVER, tl._env(t / "c3")),
            "mid_call": {},
            "planted": {},
        }
        for sig in (signal.SIGTERM, signal.SIGKILL):
            problems, seen = tl.mid_call_problems(t / f"k{sig}", sig)
            result["mid_call"][signal.Signals(sig).name] = {
                "client_error": seen["error"], "seconds_from_signal": round(seen["seconds"] or -1, 3),
                "problems": problems}
        result["planted"]["ignore-stdin-eof"] = tl.stdin_close_problems(
            tl.OFFLINE, {**offline, "LIFECYCLE_PLANT": "ignore-stdin-eof", "EDGAR13F_CACHE_DIR": str(t / "p1")}, 3.0)
        result["planted"]["exit-on-garbage"] = tl.malformed_problems(
            tl.OFFLINE, {**offline, "LIFECYCLE_PLANT": "exit-on-garbage", "EDGAR13F_CACHE_DIR": str(t / "p2")})
        result["planted"]["ignore-sigterm"] = tl.mid_call_problems(t / "p3", signal.SIGTERM, "ignore-sigterm", 3.0)[0]
        for sig in (signal.SIGTERM, signal.SIGKILL):
            result["planted"][f"partial-write/{signal.Signals(sig).name}"] = tl.mid_call_problems(
                t / f"p4{sig}", sig, "partial-write")[0]
    print(json.dumps(result, indent=1))


if __name__ == "__main__":
    main()
