"""P2 cross-check: get_holdings_as_of vs the SEC Form 13F Data Sets (NOT run in CI).

Test-time only. The server never reads the data sets: this script calls the
server's tools (live EDGAR via EdgarSource, its own cache dir) and, separately,
computes the CONTRACTS §4 answer from the data sets (SUBMISSION, COVERPAGE,
INFOTABLE). Data-set files live outside the repo (``--data``) and are never
committed.

  python -m tests.tools.datasets_crosscheck download --data DIR
  python -m tests.tools.datasets_crosscheck run --data DIR --cache DIR --n 250 --seed 20260930 \
      --out reports/artifacts/datasets_crosscheck.json

Hard rule 2: every INFOTABLE row is passed through ``blocklist.is_blocked``
before any other field is read; blocked rows are discarded and only their
count per accession is kept. The artifact carries counts, accessions and
causes only: no row values, no issuer names.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import random
import sys
import time
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from edgar13f import blocklist, config, rules, tools
from edgar13f.sec_client import SecClient
from edgar13f.sources import EdgarSource

BASE = "https://www.sec.gov/files/structureddata/data/form-13f-data-sets"
# Data sets by filing-date window covering every filing dated 2024-03-01 .. 2025-08-31.
ZIPS = (
    "01mar2024-31may2024", "01jun2024-31aug2024", "01sep2024-30nov2024",
    "01dec2024-28feb2025", "01mar2025-31may2025", "01jun2025-31aug2025",
)
PERIODS = ("2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30")
LAST_AS_OF = "2025-08-27"
ROW_KEYS = ("cusip", "value", "shares_or_principal_amount", "sh_prn", "put_call")
csv.field_size_limit(10**8)


def download(data: Path) -> None:
    data.mkdir(parents=True, exist_ok=True)
    client = SecClient(config.cache_dir(), config.user_agent())  # UA, <=5 req/s, backoff
    for name in ZIPS:
        path = data / f"{name}_form13f.zip"
        if path.exists():
            continue
        body = client.get(f"{BASE}/{name}_form13f.zip", store=False)
        if body is None:
            sys.exit(f"{name}: not found")
        path.write_bytes(body)
        print(f"{name}: {len(body)} bytes")


def _tsv(zf: zipfile.ZipFile, table: str):
    member = next(n for n in zf.namelist() if n.upper().endswith(f"{table}.TSV"))
    with zf.open(member) as fh:
        yield from csv.DictReader(io.TextIOWrapper(fh, "utf-8", errors="replace"), delimiter="\t",
                                  quoting=csv.QUOTE_NONE)


def _date(text: str) -> str | None:
    text = (text or "").strip()
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return dt.datetime.strptime(text.title() if "-" in text else text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def load_submissions(data: Path) -> dict[str, dict]:
    subs: dict[str, dict] = {}
    for name in ZIPS:
        with zipfile.ZipFile(data / f"{name}_form13f.zip") as zf:
            for r in _tsv(zf, "SUBMISSION"):
                subs[r["ACCESSION_NUMBER"]] = {
                    "accession": r["ACCESSION_NUMBER"], "cik": str(int(r["CIK"])),
                    "form": r["SUBMISSIONTYPE"].strip(), "filing_date": _date(r["FILING_DATE"]),
                    "period": _date(r["PERIODOFREPORT"]), "zip": name,
                }
            for r in _tsv(zf, "COVERPAGE"):
                s = subs.get(r["ACCESSION_NUMBER"])
                if s is not None:
                    no = (r.get("AMENDMENTNO") or "").strip()
                    s["amendment_no"] = int(no) if no.isdigit() else None
                    s["amendment_type"] = (r.get("AMENDMENTTYPE") or "").strip().upper() or None
                    s["cover_period"] = _date(r.get("REPORTCALENDARORQUARTER", ""))
    return subs


def _filing(s: dict) -> rules.Filing:
    return rules.Filing(cik=s["cik"], accession_number=s["accession"], form_type=s["form"],
                        filing_date=s["filing_date"], period_of_report=s.get("cover_period") or s["period"],
                        amendment_no=s.get("amendment_no"), amendment_type=s.get("amendment_type"))


def by_cik(subs: dict) -> dict[str, list[rules.Filing]]:
    out: dict[str, list[rules.Filing]] = defaultdict(list)
    for s in subs.values():
        if s["form"] in rules.ALL_FORMS and s["filing_date"]:
            out[s["cik"]].append(_filing(s))
    return out


def eligible(filings: list[rules.Filing], period: str) -> bool:
    """Contract §4 exclusions: no UNSPECIFIED amendment, at most one ORIGINAL."""
    v = [f for f in filings if f.form_type in rules.HOLDINGS_FORMS and f.period_of_report == period]
    return bool(v) and sum(rules.kind(f) == "ORIGINAL" for f in v) <= 1 \
        and not any(rules.kind(f) == "UNSPECIFIED" for f in v)


def sample(fil: dict[str, list[rules.Filing]], n: int, seed: int) -> list[dict]:
    """(cik, period) uniform over eligible pairs; as_of uniform in [first filing - 14 d, 2025-08-27]."""
    pairs = sorted({(f.cik, f.period_of_report) for fs in fil.values() for f in fs
                    if f.form_type in rules.HOLDINGS_FORMS and f.period_of_report in PERIODS})
    pairs = [p for p in pairs if eligible(fil[p[0]], p[1])]
    rng = random.Random(seed)
    out = []
    for cik, period in rng.sample(pairs, n):
        first = min(f.filing_date for f in fil[cik] if f.period_of_report == period)
        lo = max(dt.date.fromisoformat(first) - dt.timedelta(days=14), dt.date.fromisoformat(period))
        hi = dt.date.fromisoformat(LAST_AS_OF)
        as_of = lo + dt.timedelta(days=rng.randint(0, max((hi - lo).days, 0)))
        out.append({"cik": cik, "period": period, "as_of": as_of.isoformat()})
    return out


def restatement_strata(fil: dict[str, list[rules.Filing]], n_random: int, seed: int) -> list[dict]:
    """§4 hardening strata: for each (cik, period) with an amendment in scope, as_of = the day
    before and the day of each amendment's filing date. Every (cik, period) with a same-day
    amendment pair, a RESTATEMENT after NEW HOLDINGS, or >= 3 amendments is included; plus
    `n_random` random (cik, period) pairs with a RESTATEMENT. §4 exclusions applied."""
    groups: dict[tuple, list[rules.Filing]] = defaultdict(list)
    for fs in fil.values():
        for f in fs:
            if f.form_type in rules.HOLDINGS_FORMS and f.period_of_report in PERIODS:
                groups[(f.cik, f.period_of_report)].append(f)
    special, restated = [], []
    for key, v in sorted(groups.items()):
        if not eligible(fil[key[0]], key[1]):
            continue
        v.sort(key=rules._order)
        kinds = [rules.kind(f) for f in v]
        dates = Counter(f.filing_date for f in v)
        after_nh = "NEW HOLDINGS" in kinds and "RESTATEMENT" in kinds[kinds.index("NEW HOLDINGS"):]
        if after_nh or max(dates.values()) > 1 or len(v) >= 4:
            special.append((key, v))
        elif "RESTATEMENT" in kinds:
            restated.append((key, v))
    rng = random.Random(seed)
    chosen = special + rng.sample(restated, min(n_random, len(restated)))
    out = []
    for (cik, period), v in chosen:
        for d in sorted({f.filing_date for f in v[1:]}):
            day = dt.date.fromisoformat(d)
            for as_of, stratum in ((day - dt.timedelta(days=1), "before"), (day, "after")):
                if as_of.isoformat() <= LAST_AS_OF:
                    out.append({"cik": cik, "period": period, "as_of": as_of.isoformat(), "stratum": stratum})
    return [dict(t) for t in {tuple(sorted(t.items())): t for t in out}.values()]


def load_rows(data: Path, subs: dict, accessions: set[str]) -> tuple[dict[str, list[dict]], Counter]:
    """INFOTABLE rows for `accessions`, blocklist applied first; also redacted-row counts."""
    rows: dict[str, list[dict]] = defaultdict(list)
    redacted: Counter = Counter()
    zips = {subs[a]["zip"] for a in accessions}
    for name in ZIPS:
        if name not in zips:
            continue
        with zipfile.ZipFile(data / f"{name}_form13f.zip") as zf:
            for r in _tsv(zf, "INFOTABLE"):
                acc = r["ACCESSION_NUMBER"]
                if acc not in accessions:
                    continue
                if blocklist.is_blocked(r["NAMEOFISSUER"], r["TITLEOFCLASS"], r["CUSIP"]):
                    redacted[acc] += 1
                    continue
                rows[acc].append({
                    "cusip": r["CUSIP"].strip(), "value": _int(r["VALUE"]),
                    "shares_or_principal_amount": _int(r["SSHPRNAMT"]),
                    "sh_prn": (r["SSHPRNAMTTYPE"].strip().upper() or None),
                    "put_call": (r["PUTCALL"].strip().upper() or None),
                })
    return rows, redacted


def _int(text: str) -> int | None:
    try:
        return int(float(text)) if text.strip() else None
    except ValueError:
        return None


def expected(fil: list[rules.Filing], t: dict) -> dict:
    if not any(f.filing_date <= t["as_of"] for f in fil):
        # Ruling D1: no 13F on or before as_of -> unknown_cik. The data sets start at
        # 2024-03-01, so a CIK with only earlier 13Fs shows up here as cause "dataset_coverage".
        return {"status": "declined", "reason": "unknown_cik"}
    res = rules.resolve(fil, t["period"], t["as_of"])
    if isinstance(res, str):
        return {"status": "declined", "reason": res}
    base, sup = res
    return {"status": "ok", "accession_number": base.accession_number, "filing_date": base.filing_date,
            "source_accessions": [base.accession_number] + [s.accession_number for s in sup]}


def _multiset(rows: list[dict]) -> Counter:
    return Counter(tuple(str(r[k]).upper() if k == "cusip" else r[k] for k in ROW_KEYS) for r in rows)


def compare(got: dict, exp: dict, rows: dict, redacted: Counter) -> tuple[bool, str | None, dict]:
    info: dict = {}
    if exp.get("reason") == "unknown_cik" and got.get("reason") in ("not_yet_filed", "notice_only"):
        return False, "dataset_coverage", {"got": got["reason"], "expected": "unknown_cik"}
    if got["status"] != exp["status"] or got.get("reason") != exp.get("reason"):
        return False, "status_or_reason", {"got": got.get("reason", "ok"), "expected": exp.get("reason", "ok")}
    if exp["status"] == "declined":
        return True, None, info
    if got["source_accessions"] != exp["source_accessions"]:
        return False, "source_accessions", {"got": got["source_accessions"], "expected": exp["source_accessions"]}
    if got["filing_date"] != exp["filing_date"]:
        return False, "filing_date", {"got": got["filing_date"], "expected": exp["filing_date"]}
    want = _multiset([r for a in exp["source_accessions"] for r in rows.get(a, [])])
    have = _multiset(got["holdings"])
    info["rows"] = sum(have.values())
    info["redacted_rows_in_dataset"] = sum(redacted[a] for a in exp["source_accessions"])
    if want != have:
        cusips = {k[0] for k in (want - have) + (have - want)}
        return False, "rows", {"missing": sum((want - have).values()), "extra": sum((have - want).values()),
                               "cusips_differing": len(cusips), **info}
    return True, None, info


def wilson(k: int, n: int, z: float = 1.959964) -> list[float]:
    if n == 0:
        return [0.0, 1.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def run(args) -> None:
    subs = load_submissions(args.data)
    fil = by_cik(subs)
    if args.strata == "restatement":
        triples = restatement_strata(fil, args.n, args.seed)
    else:
        triples = sample(fil, args.n, args.seed)
    exp = [expected(fil[t["cik"]], t) for t in triples]
    need = {a for e in exp for a in e.get("source_accessions", [])}
    rows, redacted = load_rows(args.data, subs, need)
    args.cache.mkdir(parents=True, exist_ok=True)
    src = EdgarSource(SecClient(args.cache, config.user_agent()), args.cache)
    results, t0 = [], time.time()
    for i, (t, e) in enumerate(zip(triples, exp)):
        try:
            got = tools.call(src, "get_holdings_as_of", {k: t[k] for k in ("cik", "period", "as_of")})
        except Exception as exc:  # isError=true in MCP terms
            got = {"status": "error", "reason": type(exc).__name__}
        ok, cause, info = compare(got, e, rows, redacted)
        results.append({**t, "agree": ok, "cause": cause, "expected_status": e["status"], **info})
        print(f"[{i + 1}/{len(triples)}] {t} agree={ok} {cause or ''}", file=sys.stderr, flush=True)
    k = sum(r["agree"] for r in results)
    report = {
        "sample": {"n": len(results), "seed": args.seed, "periods": PERIODS, "last_as_of": LAST_AS_OF,
                   "data_sets": [f"{z}_form13f.zip" for z in ZIPS], "strata": args.strata,
                   "design": " ".join((restatement_strata if args.strata == "restatement" else sample)
                                      .__doc__.split())},
        "by_stratum": {s: {"agree": sum(r["agree"] for r in results if r.get("stratum") == s),
                           "n": sum(r.get("stratum") == s for r in results)}
                       for s in sorted({r.get("stratum") for r in results if r.get("stratum")})},
        "agreement": {"agree": k, "n": len(results), "rate": round(k / max(len(results), 1), 4),
                      "wilson_95": wilson(k, len(results))},
        "by_expected_status": dict(Counter(r["expected_status"] for r in results)),
        "disagreements_by_cause": dict(Counter(r["cause"] for r in results if not r["agree"])),
        "triples_with_redacted_rows": sum(1 for r in results if r.get("redacted_rows_in_dataset")),
        "elapsed_s": round(time.time() - t0, 1),
        "disagreements": [r for r in results if not r["agree"]],
        "results": results,
    }
    args.out.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps({k: report[k] for k in ("agreement", "disagreements_by_cause")}))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["download", "run"])
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--cache", type=Path)
    p.add_argument("--n", type=int, default=250)
    p.add_argument("--seed", type=int, default=20260930)
    p.add_argument("--strata", choices=["random", "restatement"], default="random")
    p.add_argument("--out", type=Path, default=Path("reports/artifacts/datasets_crosscheck.json"))
    a = p.parse_args()
    download(a.data) if a.cmd == "download" else run(a)


if __name__ == "__main__":
    main()
