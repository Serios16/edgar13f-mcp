"""Live old-vs-new check for stage 3 (NOT run in CI; needs network + SEC_USER_AGENT).

The same calls are answered by the v1.0.0 source and by this checkout's source, on one shared
cache dir, so both read the same EDGAR bytes; every response must be byte-identical. The calls
come from the stage-2 cross-check samples (`datasets_crosscheck.py`, same seeds): for each
(cik, period, as_of), get_holdings_as_of, diff_holdings against the previous quarter, and
list_13f_filings. `scan` counts 13F submissions in the data sets whose period of report is
after their filing date (REGISTER A17).

  python -m tests.tools.equivalence calls --data DIR --out calls.json
  python -m tests.tools.equivalence answer --calls calls.json --cache CACHE --out new.json
  PYTHONPATH=<v1.0.0 checkout>/src python -m tests.tools.equivalence answer --calls calls.json \\
      --cache CACHE --out old.json
  python -m tests.tools.equivalence compare --new new.json --old old.json --out reports/artifacts/...
  python -m tests.tools.equivalence scan --data DIR --out reports/artifacts/...

Artifacts hold call arguments, hashes, outcomes and request counts only: no rows, no values.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

from edgar13f import blocklist, config, rules, server
from edgar13f.sec_client import SecClient
from edgar13f.sources import EdgarSource


def _prev_quarter(period: str) -> str:
    d = dt.date.fromisoformat(period).replace(day=1) - dt.timedelta(days=1)  # end of previous month
    while d.month % 3:
        d = d.replace(day=1) - dt.timedelta(days=1)
    return d.isoformat()


def calls(a) -> None:
    from tests.tools import datasets_crosscheck as dc

    fil = dc.by_cik(dc.load_submissions(a.data))
    triples = dc.sample(fil, 250, 20260930) + dc.restatement_strata(fil, 20, 20260930)
    out, seen = [], set()
    for tool in ("get_holdings_as_of", "diff_holdings", "list_13f_filings"):
        for t in triples:
            args = {"get_holdings_as_of": {"cik": t["cik"], "period": t["period"], "as_of": t["as_of"]},
                    "diff_holdings": {"cik": t["cik"], "period_a": _prev_quarter(t["period"]),
                                      "period_b": t["period"], "as_of": t["as_of"]},
                    "list_13f_filings": {"cik": t["cik"], "as_of": t["as_of"]}}[tool]
            key = json.dumps([tool, args], sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append({"tool": tool, "args": args, "stratum": t.get("stratum", "random")})
    a.out.write_text(json.dumps({"triples": len(triples), "calls": out}, indent=0) + "\n")
    print(f"{len(triples)} triples, {len(out)} calls")


def answer(a) -> None:
    import edgar13f

    if not getattr(blocklist, "redacting", lambda: True)():
        sys.exit("refusing to run with redaction switched off (CLAUDE.md rule 2)")
    a.cache.mkdir(parents=True, exist_ok=True)
    src = EdgarSource(SecClient(a.cache, config.user_agent()), a.cache)
    log = a.cache / "requests.log"
    count = lambda: len(log.read_text().splitlines()) if log.exists() else 0  # noqa: E731
    items = json.loads(a.calls.read_text())["calls"]
    results = []
    for i, c in enumerate(items):
        n0, t0 = count(), time.perf_counter()
        res = server.result_for(src, c["tool"], c["args"])
        text = res.content[0].text
        body = json.loads(text) if not res.is_error else {}
        results.append({"tool": c["tool"], "args": c["args"], "is_error": bool(res.is_error),
                        "outcome": "isError" if res.is_error else body.get("reason") or body["status"],
                        "sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "requests": count() - n0, "s": round(time.perf_counter() - t0, 2)})
        print(f"[{i + 1}/{len(items)}] {c['tool']} {results[-1]['outcome']} req={results[-1]['requests']}",
              file=sys.stderr, flush=True)
    a.out.write_text(json.dumps({"edgar13f": edgar13f.__version__, "results": results}, indent=0) + "\n")


def compare(a) -> None:
    new, old = (json.loads(p.read_text()) for p in (a.new, a.old))
    pairs = list(zip(new["results"], old["results"]))
    assert all(n["args"] == o["args"] and n["tool"] == o["tool"] for n, o in pairs) and len(new["results"]) \
        == len(old["results"]), "the two runs did not answer the same calls"
    by_tool: dict = {}
    for n, o in pairs:
        s = by_tool.setdefault(n["tool"], {"calls": 0, "identical": 0, "outcomes": Counter(),
                                           "requests_new_run": 0, "requests_old_run": 0})
        s["calls"] += 1
        s["identical"] += n["sha256"] == o["sha256"] and n["is_error"] == o["is_error"]
        s["outcomes"][n["outcome"]] += 1
        s["requests_new_run"] += n["requests"]
        s["requests_old_run"] += o["requests"]
    report = {
        "new": new["edgar13f"], "old": old["edgar13f"],
        "method": "same calls, one shared cache dir; the new source answered first, then the old one; "
                  "responses compared as SHA-256 of the exact first text block",
        "identical": sum(s["identical"] for s in by_tool.values()), "calls": len(pairs),
        "by_tool": {k: {**v, "outcomes": dict(v["outcomes"])} for k, v in by_tool.items()},
        "differences": [{"tool": n["tool"], "args": n["args"], "new": n["outcome"], "old": o["outcome"]}
                        for n, o in pairs if n["sha256"] != o["sha256"] or n["is_error"] != o["is_error"]],
    }
    a.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: report[k] for k in ("identical", "calls")}))


def scan(a) -> None:
    from tests.tools import datasets_crosscheck as dc

    totals: Counter = Counter({"submissions": 0, "cover_differs_from_period": 0, "period_after_filing_date": 0})
    early = []
    for name in dc.ZIPS + dc.HISTORY:
        with zipfile.ZipFile(a.data / f"{name}_form13f.zip") as zf:
            subs = {}
            for r in dc._tsv(zf, "SUBMISSION"):
                if r["SUBMISSIONTYPE"].strip() in rules.ALL_FORMS:
                    subs[r["ACCESSION_NUMBER"]] = (r["CIK"], r["SUBMISSIONTYPE"].strip(), dc._date(r["FILING_DATE"]),
                                                   dc._date(r["PERIODOFREPORT"]), None)
            for r in dc._tsv(zf, "COVERPAGE"):
                s = subs.get(r["ACCESSION_NUMBER"])
                if s:
                    subs[r["ACCESSION_NUMBER"]] = s[:4] + (dc._date(r.get("REPORTCALENDARORQUARTER", "")),)
        for acc, (cik, form, filed, period, cover) in subs.items():
            totals["submissions"] += 1
            totals["cover_differs_from_period"] += bool(cover and period and cover != period)
            latest = max(p for p in (period, cover) if p) if (period or cover) else None
            if filed and latest and latest > filed:
                totals["period_after_filing_date"] += 1
                early.append({"accession": acc, "cik": str(int(cik)), "form": form, "filing_date": filed,
                              "period": period, "cover_period": cover, "data_set": name})
    report = {"data_sets": [f"{z}_form13f.zip" for z in dc.ZIPS + dc.HISTORY],
              "forms": list(rules.ALL_FORMS), **totals,
              "period_after_filing_in_evaluated_periods": sum(
                  1 for e in early if (e["cover_period"] or e["period"]) in dc.PERIODS),
              "period_after_filing": early}
    a.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(dict(totals)))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["calls", "answer", "compare", "scan"])
    p.add_argument("--data", type=Path)
    p.add_argument("--calls", type=Path)
    p.add_argument("--cache", type=Path)
    p.add_argument("--new", type=Path)
    p.add_argument("--old", type=Path)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    {"calls": calls, "answer": answer, "compare": compare, "scan": scan}[a.cmd](a)


if __name__ == "__main__":
    main()
