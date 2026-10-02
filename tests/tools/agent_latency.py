"""Stage 4 (c): find_manager and list_13f_filings(period) latency, and response sizes with and
without max_positions=50, on the five stage-2 filers. NOT run in CI: needs network and
SEC_USER_AGENT; caches go under --root (outside the repository).

  python -m tests.tools.agent_latency --ciks 2012383,319933,1761755,895421,1776033 \
      --root /tmp/edgar13f-stage4 --out reports/artifacts/agent_latency_run1.json

Per filer, each part in its own empty cache dir (in-process tools.call on EdgarSource, as in A15):
* find_manager(name): name = the filer's current EDGAR name (submissions JSON, read in a separate
  setup dir). Cold (empty cache: names file, every quarterly form-index prefix, current names),
  warm (same process), restart (a new process on the same cache dir: everything on disk, nothing
  in memory). Then with as_of: the filer's has_13f_filings vs list_13f_filings(cik, as_of).
* list_13f_filings(cik, as_of, period): cold, warm; then the list without period in the same dir
  (must equal it once filtered by period).
* sizes: get_holdings_as_of(period) and diff_holdings(previous quarter, period), each without and
  with max_positions=50: bytes of the first text block and of the JSON-RPC result (text +
  structuredContent), rows or changes; then the same four calls warm through the MCP Python SDK
  stdio client with SEC_USER_AGENT unset (so nothing can reach sec.gov).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from edgar13f import blocklist, config, server, tools
from edgar13f.managers import SUBMISSIONS_URL
from edgar13f.sec_client import SecClient
from edgar13f.sources import EdgarSource
from tests.tools.cold_latency import _requests, _server_env

RESTART = """
import json, sys, time
from pathlib import Path
from edgar13f import config, tools
from edgar13f.sec_client import SecClient
from edgar13f.sources import EdgarSource
cache, args = Path(sys.argv[1]), json.loads(sys.argv[2])
t0 = time.perf_counter()
out = tools.call(EdgarSource(SecClient(cache, config.user_agent()), cache), "find_manager", args)
print(json.dumps({"s": round(time.perf_counter() - t0, 2), "out": out}))
"""


def _kind(url: str) -> str:
    return ("names" if "cik-lookup" in url else "full_index" if "full-index" in url
            else "submissions" if "submissions" in url else "other")


def _src(cache: Path) -> EdgarSource:
    return EdgarSource(SecClient(cache, config.user_agent()), cache)


def _timed(src, cache: Path, tool: str, args: dict) -> tuple[dict, float, int]:
    before = len(_requests(cache))
    t0 = time.perf_counter()
    out = tools.call(src, tool, args)
    return out, round(time.perf_counter() - t0, 2), len(_requests(cache)) - before


def _rank(out: dict, cik: str) -> int | None:
    found = [c["cik"] for c in out.get("candidates", [])]
    return found.index(cik) + 1 if cik in found else None


def find_manager(root: Path, cik: str, name: str, as_of: str) -> dict:
    cache = root / f"fm-{cik}"
    src, args = _src(cache), {"name": name}
    out, cold, n = _timed(src, cache, "find_manager", args)
    r = {"query": name, "cold_s": cold, "cold_requests": n,
         "cold_requests_by_kind": dict(Counter(_kind(x["url"]) for x in _requests(cache))),
         "non_200_206": sum(1 for x in _requests(cache) if x["status"] not in (200, 206)),
         "candidates": len(out["candidates"]), "rank": _rank(out, cik),
         "has_13f_filings": next((c["has_13f_filings"] for c in out["candidates"] if c["cik"] == cik), None)}
    warm, r["warm_s"], r["warm_requests"] = _timed(src, cache, "find_manager", args)
    r["warm_same_answer"] = warm == out
    before = len(_requests(cache))
    proc = subprocess.run([sys.executable, "-c", RESTART, str(cache), json.dumps(args)], capture_output=True,
                          text=True, env=_server_env(cache, config.user_agent()), check=True)
    res = json.loads(proc.stdout)
    r.update(restart_s=res["s"], restart_requests=len(_requests(cache)) - before,
             restart_same_answer=res["out"] == out)
    dated, r["as_of_s"], r["as_of_requests"] = _timed(src, cache, "find_manager", {**args, "as_of": as_of})
    r["as_of_rank"] = _rank(dated, cik)
    r["as_of_has_13f_filings"] = next((c["has_13f_filings"] for c in dated["candidates"] if c["cik"] == cik), None)
    return r


def list_period(root: Path, cik: str, period: str, as_of: str) -> dict:
    cache = root / f"list-{cik}"
    src = _src(cache)
    args = {"cik": cik, "as_of": as_of, "period": period}
    out, cold, n = _timed(src, cache, "list_13f_filings", args)
    r = {"status": out["status"], "filings": len(out.get("filings", [])), "cold_s": cold, "cold_requests": n}
    again, r["warm_s"], r["warm_requests"] = _timed(src, cache, "list_13f_filings", args)
    full, r["full_list_after_s"], r["full_list_after_requests"] = _timed(
        src, cache, "list_13f_filings", {"cik": cik, "as_of": as_of})
    r["full_list_filings"] = len(full.get("filings", []))
    r["equals_full_list_filtered"] = out == {**full, "filings": [f for f in full["filings"]
                                                                 if f["period_of_report"] == period]}
    r["non_200"] = sum(1 for x in _requests(cache) if x["status"] != 200)
    return r


def _sizes(src, tool: str, args: dict) -> dict:
    res = server.result_for(src, tool, args)
    body = json.loads(res.content[0].text)
    rpc = json.dumps(res.model_dump(mode="json", by_alias=True, exclude_none=True), ensure_ascii=False)
    items = body.get("holdings", body.get("changes", []))
    return {"status": body["status"], "text_bytes": len(res.content[0].text.encode()), "jsonrpc_result_bytes":
            len(rpc.encode()), "items": len(items), "total_positions": body.get("total_positions"),
            "truncated": body.get("truncated")}


def _sdk_calls(cache: Path, calls: list[tuple[str, dict]]) -> list[float]:
    import anyio
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    async def run() -> list[float]:
        params = StdioServerParameters(command=sys.executable, args=["-m", "edgar13f.server"],
                                       env=_server_env(cache, None))
        out = []
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for tool, args in calls:
                    t0 = time.perf_counter()
                    res = await session.call_tool(tool, args)
                    assert res.is_error is False
                    out.append(round(time.perf_counter() - t0, 2))
        return out

    return anyio.run(run)


def sizes(root: Path, cik: str, prev: str, period: str, as_of: str) -> dict:
    cache = root / f"size-{cik}"
    src = _src(cache)
    calls = [("get_holdings_as_of", {"cik": cik, "period": period, "as_of": as_of}),
             ("diff_holdings", {"cik": cik, "period_a": prev, "period_b": period, "as_of": as_of})]
    calls = [c for t, a in calls for c in ((t, a), (t, {**a, "max_positions": 50}))]
    r = {f"{t}{'_max50' if 'max_positions' in a else ''}": _sizes(src, t, a) for t, a in calls}
    for (t, a), s in zip(calls, _sdk_calls(cache, calls)):
        r[f"{t}{'_max50' if 'max_positions' in a else ''}"]["sdk_stdio_warm_s"] = s
    return r


def main() -> None:
    if not blocklist.redacting():
        sys.exit("refusing to run with redaction switched off (CLAUDE.md rule 2)")
    p = argparse.ArgumentParser()
    p.add_argument("--ciks", required=True)
    p.add_argument("--root", type=Path, required=True, help="cache root outside the repository")
    p.add_argument("--period", default="2025-03-31")
    p.add_argument("--prev", default="2024-12-31")
    p.add_argument("--as-of", default="2025-08-27")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--skip-sizes", action="store_true")
    a = p.parse_args()
    setup = SecClient(a.root / "setup", config.user_agent())
    results = []
    for cik in [c.strip() for c in a.ciks.split(",") if c.strip()]:
        name = json.loads(setup.get(SUBMISSIONS_URL.format(cik=int(cik))))["name"]
        r = {"cik": cik, "find_manager": find_manager(a.root, cik, name, a.as_of),
             "list_period": list_period(a.root, cik, a.period, a.as_of)}
        if not a.skip_sizes:
            r["sizes"] = sizes(a.root, cik, a.prev, a.period, a.as_of)
        results.append(r)
        print(json.dumps(r), flush=True)
    import edgar13f

    a.out.write_text(json.dumps({"edgar13f": edgar13f.__version__, "period": a.period, "prev": a.prev,
                                 "as_of": a.as_of, "min_interval_s": 0.25, "results": results}, indent=1) + "\n")


if __name__ == "__main__":
    main()
