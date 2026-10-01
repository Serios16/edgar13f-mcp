"""Measure cold-cache latency of get_holdings_as_of for large filers (NOT run in CI).

Measurement only; nothing is tuned. Needs network + SEC_USER_AGENT and a local copy
of one SEC Form 13F Data Sets zip (only to pick the filers; the server never reads it).

  python -m tests.tools.cold_latency --zip DIR/01mar2025-31may2025_form13f.zip \
      --period 2025-03-31 --as-of 2025-08-27 --n 5 --out reports/artifacts/cold_latency.json
  python -m tests.tools.cold_latency --ciks 2012383,319933,... --out reports/artifacts/cold_latency_<label>.json

Filers: the n CIKs whose 13F-HR for `period` has the most information-table rows left
after blocklist redaction (hard rule 2 is applied to every row before it is counted), or
the CIKs given with --ciks (no data set needed; used to re-measure the same filers).
For each: a fresh empty cache dir; one in-process tools.call (no stdio) cold, then the
same call warm. Requests are counted from the cache dir's requests.log. With --ciks,
list_13f_filings is also measured, cold in a second fresh cache dir, then warm.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path

from edgar13f import blocklist, config, rules, tools
from edgar13f.sec_client import SecClient
from edgar13f.sources import EdgarSource
from tests.tools.datasets_crosscheck import _date, _tsv


def largest(zip_path: Path, period: str, n: int) -> list[tuple[str, str, int]]:
    with zipfile.ZipFile(zip_path) as zf:
        subs = {r["ACCESSION_NUMBER"]: str(int(r["CIK"])) for r in _tsv(zf, "SUBMISSION")
                if r["SUBMISSIONTYPE"].strip() == "13F-HR" and _date(r["PERIODOFREPORT"]) == period}
        rows: Counter = Counter()
        for r in _tsv(zf, "INFOTABLE"):
            if r["ACCESSION_NUMBER"] not in subs:
                continue
            if blocklist.is_blocked(r["NAMEOFISSUER"], r["TITLEOFCLASS"], r["CUSIP"]):
                continue
            rows[r["ACCESSION_NUMBER"]] += 1
    return [(subs[a], a, k) for a, k in rows.most_common(n)]


def _requests(cache: Path) -> list[dict]:
    log = cache / "requests.log"
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def _timed(src, cache: Path, tool: str, args: dict, out: dict, prefix: str = "") -> dict:
    for phase in ("cold", "warm"):
        before = len(_requests(cache))
        t0 = time.perf_counter()
        res = tools.call(src, tool, args)
        out[f"{prefix}{phase}_s"] = round(time.perf_counter() - t0, 2)
        out[f"{prefix}{phase}_requests"] = len(_requests(cache)) - before
    return res


def measure_list(cik: str, as_of: str, out: dict) -> None:
    cache = Path(tempfile.mkdtemp(prefix="edgar13f-latency-list-"))
    src = EdgarSource(SecClient(cache, config.user_agent()), cache)
    res = _timed(src, cache, "list_13f_filings", {"cik": cik, "as_of": as_of}, out, "list_")
    out["list_status"] = res["status"]
    out["filings_visible"] = len(res.get("filings", []))
    out["list_non_200"] = sum(1 for r in _requests(cache) if r["status"] != 200)


def r_src_filings(cik: str, as_of: str) -> list:
    cache = Path(tempfile.mkdtemp(prefix="edgar13f-latency-count-"))
    src = EdgarSource(SecClient(cache, config.user_agent()), cache)
    return rules.visible_filings(src.filings(cik, as_of) or [], as_of)


def measure(cik: str, period: str, as_of: str) -> dict:
    cache = Path(tempfile.mkdtemp(prefix="edgar13f-latency-"))
    src = EdgarSource(SecClient(cache, config.user_agent()), cache)
    args = {"cik": cik, "period": period, "as_of": as_of}
    out = {"cik": cik}
    res = _timed(src, cache, "get_holdings_as_of", args, out)
    reqs = _requests(cache)
    out.update(status=res["status"], rows_returned=len(res.get("holdings", [])),
               source_accessions=res.get("source_accessions"),
               cold_requests_by_kind=dict(Counter(r["url"].rsplit(".", 1)[-1] for r in reqs)),
               non_200=sum(1 for r in reqs if r["status"] != 200))
    return out


def main() -> None:
    if not blocklist.redacting():
        sys.exit("refusing to run with redaction switched off (CLAUDE.md rule 2)")
    p = argparse.ArgumentParser()
    p.add_argument("--zip", type=Path)
    p.add_argument("--ciks", help="comma-separated CIKs to measure instead of picking from --zip")
    p.add_argument("--period", default="2025-03-31")
    p.add_argument("--as-of", default="2025-08-27")
    p.add_argument("--n", type=int, default=5)
    p.add_argument("--out", type=Path, default=Path("reports/artifacts/cold_latency.json"))
    a = p.parse_args()
    if a.ciks:
        picks = [(c.strip(), None, None) for c in a.ciks.split(",") if c.strip()]
        selection = "CIKs given with --ciks"
    else:
        picks = largest(a.zip, a.period, a.n)
        selection = f"top {a.n} 13F-HR by rows after redaction in {a.zip.name}"
    results = []
    for cik, acc, n_rows in picks:
        r = measure(cik, a.period, a.as_of)
        if acc:
            r["dataset_13f_hr"] = acc
            r["dataset_rows_after_redaction"] = n_rows
            r["filings_visible"] = len(r_src_filings(cik, a.as_of))
        else:
            measure_list(cik, a.as_of, r)
        results.append(r)
        print(json.dumps(r), flush=True)
    report = {"period": a.period, "as_of": a.as_of, "selection": selection,
              "call": "in-process tools.call, empty cache dir per filer and per tool",
              "min_interval_s": 0.25, "results": results}
    a.out.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    main()
