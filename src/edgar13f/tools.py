"""The contract tools (CONTRACTS §1, §5, §6; Addendum A), independent of transport."""

from __future__ import annotations

from . import DISCLAIMER, managers, narrow, rules
from .validate import Decline, validate


def _ok(**fields) -> dict:
    return {"status": "ok", "disclaimer": DISCLAIMER, **fields}


def _decline(d: Decline) -> dict:
    return {"status": "declined", "disclaimer": DISCLAIMER, "reason": d.reason, "message": d.message}


def _visible_13f(source, cik: str, as_of: str, periods: tuple | None = None) -> list[rules.Filing] | Decline:
    filings = source.filings(cik, as_of, periods)
    vis = rules.visible_filings(filings or [], as_of)
    vis = [f for f in vis if f.form_type in rules.ALL_FORMS]
    if not vis:
        return Decline("unknown_cik", f"CIK {cik} has no Form 13F filing on or before {as_of}")
    return vis


def list_13f_filings(source, args: dict) -> dict:
    a, err = validate("list_13f_filings", args)
    if err:
        return _decline(err)
    period = a.get("period")
    vis = _visible_13f(source, a["cik"], a["as_of"], (period,) if period else None)
    if isinstance(vis, Decline):
        return _decline(vis)
    if period:  # A3: the same visible list, filtered by period of report
        vis = [f for f in vis if f.period_of_report == period]
    return _ok(cik=a["cik"], as_of=a["as_of"], filings=[f.record() for f in vis])


def _holdings(source, filings: list[rules.Filing], period: str, as_of: str, a: dict):
    res = rules.resolve(filings, period, as_of)
    if isinstance(res, str):
        msg = {
            "notice_only": f"Only a 13F notice is visible for {period}: holdings are reported by another manager",
            "not_yet_filed": f"No 13F-HR/13F-HR/A for {period} is visible on {as_of}",
        }[res]
        return Decline(res, msg)
    base, supplements = res
    sources = [base, *supplements]
    rows = [r for f in sources for r in source.rows(f)]
    cusips, issuer = a.get("cusip"), a.get("issuer")
    if cusips is not None or issuer is not None:
        rows = [r for r in rows if narrow.keep(r, cusips, issuer)]
    return base, [f.accession_number for f in sources], rows


def get_holdings_as_of(source, args: dict) -> dict:
    a, err = validate("get_holdings_as_of", args)
    if err:
        return _decline(err)
    vis = _visible_13f(source, a["cik"], a["as_of"], (a["period"],))
    if isinstance(vis, Decline):
        return _decline(vis)
    res = _holdings(source, vis, a["period"], a["as_of"], a)
    if isinstance(res, Decline):
        return _decline(res)
    base, accessions, rows = res
    rows, extra = narrow.holdings(a, rows)
    return _ok(
        cik=a["cik"], period=a["period"], as_of=a["as_of"],
        accession_number=base.accession_number, source_accessions=accessions,
        filing_date=base.filing_date, **extra, holdings=rows,
    )


def _consolidate(rows: list[dict]) -> dict[tuple, dict]:
    out: dict[tuple, dict] = {}
    for r in rows:
        key = (r["cusip"].upper(), r["put_call"], r["sh_prn"])
        agg = out.setdefault(key, {"cusip": r["cusip"], "name": r["name_of_issuer"], "shares": 0, "value": 0})
        agg["shares"] += r["shares_or_principal_amount"] or 0
        agg["value"] += r["value"] or 0
    return out


def _change_type(in_a: bool, in_b: bool, delta: int) -> str:
    if not in_a:
        return "added"
    if not in_b:
        return "removed"
    return "increased" if delta > 0 else "decreased" if delta < 0 else "unchanged"


def diff_holdings(source, args: dict) -> dict:
    a, err = validate("diff_holdings", args)
    if err:
        return _decline(err)
    vis = _visible_13f(source, a["cik"], a["as_of"], (a["period_a"], a["period_b"]))
    if isinstance(vis, Decline):
        return _decline(vis)
    side = []
    for period in (a["period_a"], a["period_b"]):
        res = _holdings(source, vis, period, a["as_of"], a)
        if isinstance(res, Decline):
            return _decline(res)
        side.append(res)
    (base_a, acc_a, rows_a), (base_b, acc_b, rows_b) = side
    cons_a, cons_b = _consolidate(rows_a), _consolidate(rows_b)
    changes = []
    for key in list(cons_a) + [k for k in cons_b if k not in cons_a]:
        ra, rb = cons_a.get(key), cons_b.get(key)
        sa, sb = (ra or {}).get("shares", 0), (rb or {}).get("shares", 0)
        va, vb = (ra or {}).get("value", 0), (rb or {}).get("value", 0)
        changes.append({
            "cusip": (rb or ra)["cusip"], "name_of_issuer": (rb or ra)["name"], "put_call": key[1], "sh_prn": key[2],
            "shares_a": sa, "shares_b": sb, "shares_delta": sb - sa,
            "value_a": va, "value_b": vb, "value_delta": vb - va,
            "change_type": _change_type(ra is not None, rb is not None, sb - sa),
        })
    changes, extra = narrow.changes(a, rows_a + rows_b, changes)
    return _ok(
        cik=a["cik"], period_a=a["period_a"], period_b=a["period_b"], as_of=a["as_of"],
        accession_a=base_a.accession_number, accession_b=base_b.accession_number,
        source_accessions_a=acc_a, source_accessions_b=acc_b, **extra, changes=changes,
    )


def find_manager(source, args: dict) -> dict:
    a, err = validate("find_manager", args)
    if err:
        return _decline(err)
    return _ok(**managers.find(source.directory, a))


TOOLS = {
    "list_13f_filings": list_13f_filings,
    "get_holdings_as_of": get_holdings_as_of,
    "diff_holdings": diff_holdings,
    "find_manager": find_manager,
}


def call(source, name: str, args: dict | None) -> dict:
    return TOOLS[name](source, {} if args is None else args)
