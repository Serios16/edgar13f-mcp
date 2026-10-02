"""Stage 4: find_manager's has_13f_filings (EDGAR quarterly form indexes) against
list_13f_filings (submissions JSON), live. NOT run in CI: needs network and SEC_USER_AGENT.

  python -m tests.tools.has13f_crosscheck --cache <dir outside the repo> --n 150 --seed 4 \
      --out reports/artifacts/has13f_crosscheck.json

Sample (seeded): n CIKs from the 13F index (every CIK with a 13F-HR/HR-A/NT/NT-A since 1993) and
n CIKs from EDGAR's CIK lookup file that are not in it. For an index CIK with earliest 13F date F,
as_of is F - 1 day, F, and one random date between F and the cut-off; for the others, the
cut-off (two days before the run). Expected: list_13f_filings(cik, as_of, period=<the quarter end
on or after as_of>) is ok exactly when has_13f_filings is true (unknown_cik otherwise). The
period makes the list call cheap (no cover page of an older filing is read) without changing
unknown_cik (REGISTER A17).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
from pathlib import Path

from edgar13f import blocklist, config, managers, tools
from edgar13f.sec_client import SecClient
from edgar13f.sources import EdgarSource


def quarter_end(day: dt.date) -> str:
    q = (day.month - 1) // 3 + 1
    return (dt.date(day.year + q // 4, 3 * q % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()


def main() -> None:
    if not blocklist.redacting():
        sys.exit("refusing to run with redaction switched off (CLAUDE.md rule 2)")
    p = argparse.ArgumentParser()
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--n", type=int, default=150)
    p.add_argument("--seed", type=int, default=4)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    src = EdgarSource(SecClient(a.cache, config.user_agent()), a.cache)
    first = dict(src.directory.first_13f(None))
    text, _ = src.directory._lookup()
    lookup = {str(int(line.rstrip(":").rpartition(":")[2])) for line in text.split("\n") if line.count(":") >= 2}
    cutoff = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=2)
    rng = random.Random(a.seed)
    filers = rng.sample(sorted(c for c, d in first.items() if d <= cutoff.isoformat()), a.n)
    others = rng.sample(sorted(lookup - set(first)), a.n)
    cases = []
    for cik in filers:
        f = dt.date.fromisoformat(first[cik])
        rand = f + dt.timedelta(days=rng.randrange((cutoff - f).days + 1))
        cases += [(cik, f - dt.timedelta(days=1), "first-1"), (cik, f, "first"), (cik, rand, "random")]
    cases += [(cik, cutoff, "not_in_index") for cik in others]
    results, t0 = [], time.time()
    for cik, day, kind in cases:
        as_of = day.isoformat()
        has = managers._has(cik, first.get(cik), as_of)
        out = tools.call(src, "list_13f_filings", {"cik": cik, "as_of": as_of, "period": quarter_end(day)})
        listed = out["status"] == "ok"
        results.append({"cik": cik, "as_of": as_of, "kind": kind, "first_13f": first.get(cik),
                        "has_13f_filings": has, "list": out["status"] if listed else out["reason"], "agree": has == listed})
    log = [json.loads(x) for x in (a.cache / "requests.log").read_text().splitlines()]
    report = {"seed": a.seed, "n_per_group": a.n, "cutoff": cutoff.isoformat(), "index_ciks": len(first),
              "cases": len(results), "agree": sum(r["agree"] for r in results),
              "by_kind": {k: {"cases": sum(r["kind"] == k for r in results),
                              "agree": sum(r["agree"] for r in results if r["kind"] == k)}
                          for k in ("first-1", "first", "random", "not_in_index")},
              "disagreements": [r for r in results if not r["agree"]],
              "seconds": round(time.time() - t0, 1),
              "requests_in_cache_log": len(log),
              "non_200_206": sum(1 for x in log if x["status"] not in (200, 206))}
    a.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "disagreements"}, indent=1))
    print(json.dumps(report["disagreements"][:20], indent=1))


if __name__ == "__main__":
    main()
