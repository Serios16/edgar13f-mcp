"""Stage 5 (b): SIGKILL / SIGTERM at random moments of a call, then check the cache (offline).

    python -m tests.tools.kill_fuzz --runs 200 --inflate 4000 --seed 5 --out reports/artifacts/kill_fuzz.json

Each run: a fresh cache, `tests.invariants.lifecycle_server` (real EdgarSource/SecClient, offline opener,
every information table repeated `--inflate` times so cache writes are large), one get_holdings_as_of
call, the signal after a uniform random delay in [0, the measured call time], then
`test_lifecycle.cache_problems` and a fresh start on the same cache that must answer correctly.
"""

from __future__ import annotations

import argparse
import json
import random
import signal
import tempfile
import time
from collections import Counter
from pathlib import Path

from tests.invariants import test_lifecycle as tl


def one(cache: Path, inflate: int, sig: int | None, delay: float) -> tuple[list[str], float]:
    env = {k: v for k, v in tl._env(cache, LIFECYCLE_INFLATE=str(inflate)).items() if k != "EDGAR13F_FIXTURE_DIR"}
    raw = tl.Raw(tl.OFFLINE, env)
    try:
        raw.handshake()
        start = time.monotonic()
        if sig is None:
            resp, _ = raw.request("tools/call", {"name": tl.CALL[0], "arguments": tl.CALL[1]}, timeout=120)
            return ([] if resp else ["no answer"]), time.monotonic() - start
        raw.send({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tl.CALL[0],
                                                                                 "arguments": tl.CALL[1]}})
        time.sleep(delay)
        raw.proc.send_signal(sig)
        raw.proc.wait(30)
    finally:
        raw.close()
    problems = tl.cache_problems(cache, inflate)
    fresh = tl.Raw(tl.OFFLINE, env)
    try:
        fresh.handshake()
        resp, _ = fresh.request("tools/call", {"name": tl.CALL[0], "arguments": tl.CALL[1]}, timeout=120)
        result = (resp or {}).get("result", {})
        if result.get("isError") is not False or result.get("structuredContent", {}).get("status") != "ok":
            problems.append(f"fresh start: no correct answer: {str(resp)[:200]}")
    finally:
        fresh.close()
    return problems, delay


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--inflate", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    with tempfile.TemporaryDirectory() as tmp:
        _, call_time = one(Path(tmp) / "warm", args.inflate, None, 0.0)
        runs, kinds = [], Counter()
        for i in range(args.runs):
            sig = (signal.SIGKILL, signal.SIGTERM)[i % 2]
            delay = rnd.uniform(0.0, call_time)
            problems, _ = one(Path(tmp) / f"run{i}", args.inflate, sig, delay)
            kinds.update(p.split(":")[0] for p in problems)
            runs.append({"signal": signal.Signals(sig).name, "delay_s": round(delay, 4), "problems": problems})
    out = {"command": f"python -m tests.tools.kill_fuzz --runs {args.runs} --inflate {args.inflate} --seed {args.seed}",
           "call_time_s": round(call_time, 3), "runs": len(runs),
           "runs_with_problems": sum(bool(r["problems"]) for r in runs), "problem_kinds": dict(kinds),
           "per_run": runs}
    text = json.dumps(out, indent=1)
    if args.out:
        args.out.write_text(text + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "per_run"}, indent=1))


if __name__ == "__main__":
    main()
