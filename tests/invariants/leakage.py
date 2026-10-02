"""Leakage invariant engine (CONTRACTS §3, §4, §7; Addendum A) over recorded fixtures.

A case is (cik, pivot filing F, as_of) with as_of in {F.filing_date - 1, F.filing_date,
F.filing_date + 1}. For each case the tools are called and every returned or cited
accession is checked against the fixture's filing dates, plus an independent oracle for
§4 (base + supplements) and the pivot's visibility. Stage 4 adds, per case, the Addendum A
parameters (issuer, max_positions, list period, agent mode) and find_manager(as_of), whose
has_13f_filings must equal "earliest 13F filing in the fixture <= as_of" for every candidate.
Each violation names its category (second word) so the controls can be checked per category.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from functools import lru_cache
from pathlib import Path

from edgar13f import tools
from edgar13f.rules import ALL_FORMS
from edgar13f.sources import FixtureSource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ROW_PERIODS = ("2023-09-30", "2025-09-30")  # periods with recorded information tables
PIVOT_FROM = "2023-10-01"


def _shift(date: str, days: int) -> str:
    return (dt.date.fromisoformat(date) + dt.timedelta(days=days)).isoformat()


def prev_quarter(period: str) -> str:
    d = dt.date.fromisoformat(period).replace(day=1) - dt.timedelta(days=1)
    while d.month % 3:
        d = d.replace(day=1) - dt.timedelta(days=1)
    return d.isoformat()


@lru_cache(maxsize=None)
def _load(cik: str) -> str:
    return (FIXTURES / cik / "filings.json").read_text()


def load(cik: str) -> list[dict]:
    return json.loads(_load(cik))["filings"]


@lru_cache(maxsize=None)
def first_13f() -> dict[str, str]:
    """Oracle for find_manager: earliest 13F filing date of every fixture manager."""
    out = {}
    for d in FIXTURES.iterdir():
        if (d / "filings.json").exists():
            dates = [f["filing_date"] for f in load(d.name) if f["form_type"] in ALL_FORMS]
            if dates:
                out[d.name] = min(dates)
    return out


def categories(violations: list[str]) -> set[str]:
    return {v.split()[1].rstrip(":") for v in violations}


def oracle(filings: list[dict], period: str, as_of: str) -> list[str] | str:
    """Independent statement of §4: [base, *supplements] accessions, or decline reason."""
    v = [f for f in filings if f["filing_date"] <= as_of and f["period_of_report"] == period]
    hr = [f for f in v if f["form_type"] in ("13F-HR", "13F-HR/A")]
    if not hr:
        return "notice_only" if any(f["form_type"].startswith("13F-NT") for f in v) else "not_yet_filed"
    hr.sort(key=lambda f: (f["filing_date"], f["amendment_no"] is not None, f["amendment_no"] or 0,
                           f["accession_number"]))
    bases = [i for i, f in enumerate(hr) if f["form_type"] == "13F-HR" or f["amendment_type"] != "NEW HOLDINGS"]
    if not bases:
        return "not_yet_filed"
    b = bases[-1]
    return [hr[b]["accession_number"]] + [f["accession_number"] for f in hr[b + 1:]
                                          if f["amendment_type"] == "NEW HOLDINGS"]


def cases() -> list[tuple[str, dict, str]]:
    out, seen = [], set()
    for d in sorted(p.name for p in FIXTURES.iterdir() if (p / "filings.json").exists()):
        for f in load(d):
            if f["filing_date"] < PIVOT_FROM:
                continue
            for delta in (-1, 0, 1):
                key = (d, f["accession_number"], delta)
                if key not in seen:
                    seen.add(key)
                    out.append((d, f, _shift(f["filing_date"], delta)))
    return out


def _cited(resp: dict) -> set[str]:
    accs = set()
    for key in ("accession_number", "accession_a", "accession_b"):
        if resp.get(key):
            accs.add(resp[key])
    for key in ("source_accessions", "source_accessions_a", "source_accessions_b"):
        accs.update(resp.get(key) or [])
    for row in resp.get("holdings") or []:
        accs.add(row["accession_number"])
    for rec in resp.get("filings") or []:
        accs.add(rec["accession_number"])
    return accs


def check_case(source, cik: str, pivot: dict, as_of: str, stats: dict | None = None) -> list[str]:
    stats = {} if stats is None else stats
    filings = load(cik)
    fdate = {f["accession_number"]: f["filing_date"] for f in filings}
    v: list[str] = []
    tag = f"{cik}/{pivot['accession_number']}@{as_of}"

    def leaks(name: str, resp: dict) -> None:
        for acc in sorted(_cited(resp)):
            if fdate.get(acc, "9999-12-31") > as_of:
                v.append(f"{tag} {name}: cites {acc} filed {fdate.get(acc)}")

    def run(name: str, tool: str, args: dict) -> dict:
        resp = tools.call(source, tool, args)
        leaks(name, resp)
        stats[name] = stats.get(name, 0) + 1
        return resp

    listed = run("list", "list_13f_filings", {"cik": cik, "as_of": as_of})
    present = pivot["accession_number"] in {r["accession_number"] for r in listed.get("filings", [])}
    if present != (pivot["filing_date"] <= as_of):
        v.append(f"{tag} list: pivot presence {present}")
    period = pivot["period_of_report"]
    _find_manager(source, cik, as_of, tag, v, stats)
    if period:  # A3: the visible filings of one period, nothing else
        got = run("list_period", "list_13f_filings", {"cik": cik, "as_of": as_of, "period": period})
        want = sorted(f["accession_number"] for f in filings if f["filing_date"] <= as_of
                      and f["period_of_report"] == period and f["form_type"] in ALL_FORMS)
        have = sorted(r["accession_number"] for r in got["filings"]) if got["status"] == "ok" else got["reason"]
        if have != (want if listed["status"] == "ok" else listed["reason"]):
            v.append(f"{tag} list_period: expected {want}, got {have}")
    if not (period and ROW_PERIODS[0] <= period <= ROW_PERIODS[1]):
        return v
    expect = oracle(filings, period, as_of)
    if listed["status"] == "declined":
        expect = listed["reason"]
    base = {"cik": cik, "period": period, "as_of": as_of}
    for name, extra in (("holdings", {}), ("holdings_issuer", {"issuer": "inc", "max_positions": 5}),
                        ("holdings_max", {"max_positions": 1}), ("holdings_agent", None)):
        if extra is None:
            os.environ["EDGAR13F_AGENT_MODE"] = "on"
        try:
            held = run(name, "get_holdings_as_of", {**base, **(extra or {})})
        finally:
            os.environ.pop("EDGAR13F_AGENT_MODE", None)
        got = held.get("source_accessions") if held["status"] == "ok" else held.get("reason")
        if got != expect:
            v.append(f"{tag} {name}: expected {expect}, got {got}")
        if held["status"] != "ok" and held.get("holdings"):
            v.append(f"{tag} {name}: holdings returned while declined")
        if held["status"] == "ok" and not {r["accession_number"] for r in held["holdings"]} <= set(got):
            v.append(f"{tag} {name}: a row cites a filing outside source_accessions")
    prev = prev_quarter(period)
    if prev >= ROW_PERIODS[0]:
        args = {"cik": cik, "period_a": prev, "period_b": period, "as_of": as_of}
        run("diff", "diff_holdings", args)
        run("diff_narrowed", "diff_holdings", {**args, "issuer": "co", "max_positions": 3})
    return v


def _find_manager(source, cik: str, as_of: str, tag: str, v: list[str], stats: dict) -> None:
    """A4: has_13f_filings as of as_of, for this manager and every other candidate found."""
    names = [f["filing_manager_name"] for f in load(cik) if f["filing_manager_name"]]
    if not names:
        return
    out = tools.call(source, "find_manager", {"name": names[0], "as_of": as_of, "limit": 20})
    stats["find_manager"] = stats.get("find_manager", 0) + 1
    found = {c["cik"]: c["has_13f_filings"] for c in out["candidates"]}
    if cik not in found:
        v.append(f"{tag} find_manager: manager not found by its own name")
    for c, has in found.items():
        if has != (first_13f().get(c, "9999-12-31") <= as_of):
            v.append(f"{tag} find_manager: {c} has_13f_filings {has} (first 13F {first_13f().get(c)})")


def run_suite(source=None, stats: dict | None = None) -> tuple[int, list[str]]:
    source = source or FixtureSource(FIXTURES)
    all_cases = cases()
    violations: list[str] = []
    for cik, pivot, as_of in all_cases:
        violations.extend(check_case(source, cik, pivot, as_of, stats))
    return len(all_cases), violations
