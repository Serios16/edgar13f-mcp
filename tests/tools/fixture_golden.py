"""Golden responses over every recorded and synthetic fixture (stage 3, redaction switch).

The grid below is derived from the fixture files only (never from server output). For each
(tool, arguments) the golden holds the SHA-256 of the exact text the server returns
(`server.result_for`, first text block) plus the isError flag. It was written once by the
v1.0.0 source and is compared by `tests/unit/test_golden.py` with EDGAR13F_REDACT unset.

  git archive v1.0.0 src | tar -x -C <dir>
  PYTHONPATH=<dir>/src python -m tests.tools.fixture_golden --label "v1.0.0 (b208c47)" \
      --out tests/golden/v1_0_fixture_responses.json

The golden holds hashes only: no rows, no values.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")
FAR_DATES = ("1999-12-31", "2025-08-27", "2099-12-31")


def _day_before(d: str) -> str:
    return (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()


def _managers() -> list[tuple[Path, str]]:
    roots = [FIXTURES, FIXTURES / "synthetic"]
    return [(root, d.name) for root in roots for d in sorted(root.iterdir()) if (d / "filings.json").exists()]


def _rows(root: Path, cik: str, accession: str) -> list[dict]:
    path = root / cik / "rows" / f"{accession}.json"
    return json.loads(path.read_text()) if path.exists() else []


def grid() -> list[tuple[str, str, dict]]:
    """(fixture root name, tool, arguments), deterministic."""
    out: list[tuple[str, str, dict]] = []
    for root, cik in _managers():
        tag = root.name
        filings = json.loads((root / cik / "filings.json").read_text())["filings"]
        dates = sorted({d for f in filings for d in (f["filing_date"], _day_before(f["filing_date"]))}
                       | set(FAR_DATES))
        for as_of in dates:
            out.append((tag, "list_13f_filings", {"cik": cik, "as_of": as_of}))
        with_rows = {f["accession_number"] for f in filings
                     if (root / cik / "rows" / f"{f['accession_number']}.json").exists()}
        periods = sorted({f["period_of_report"] for f in filings
                          if f["accession_number"] in with_rows and f["period_of_report"]})
        for period in periods:
            mine = [f for f in filings if f["period_of_report"] == period]
            as_ofs = sorted({d for f in mine for d in (f["filing_date"], _day_before(f["filing_date"]))}
                            | {period, "2025-08-27"})
            for as_of in as_ofs:
                out.append((tag, "get_holdings_as_of", {"cik": cik, "period": period, "as_of": as_of}))
            rows = [r for f in mine for r in _rows(root, cik, f["accession_number"])]
            cusips = sorted({r["cusip"] for r in rows})[:2]
            if cusips:
                pick = [cusips[0].lower()] + cusips[1:] + ["000000000"]
                out.append((tag, "get_holdings_as_of",
                            {"cik": cik, "period": period, "as_of": "2025-08-27", "cusip": pick}))
        notices = sorted({f["period_of_report"] for f in filings
                          if f["form_type"].startswith("13F-NT") and f["period_of_report"]} - set(periods))
        for period in notices[-4:]:
            mine = [f for f in filings if f["period_of_report"] == period]
            for as_of in sorted({f["filing_date"] for f in mine} | {"2025-08-27"}):
                out.append((tag, "get_holdings_as_of", {"cik": cik, "period": period, "as_of": as_of}))
        for a, b in zip(periods, periods[1:]):
            mine = [f for f in filings if f["period_of_report"] in (a, b)]
            for as_of in sorted({f["filing_date"] for f in mine} | {"2025-08-27"}):
                out.append((tag, "diff_holdings", {"cik": cik, "period_a": a, "period_b": b, "as_of": as_of}))
            cusips = sorted({r["cusip"] for f in mine for r in _rows(root, cik, f["accession_number"])})[:3]
            if cusips:
                out.append((tag, "diff_holdings", {"cik": cik, "period_a": a, "period_b": b,
                                                   "as_of": "2025-08-27", "cusip": cusips}))
    first = _managers()[0][1]
    for tool, args in [
        ("list_13f_filings", {"cik": "0999999999", "as_of": "2025-01-01"}),
        ("list_13f_filings", {"cik": "0" + first, "as_of": "2025-01-01"}),
        ("list_13f_filings", {"cik": first, "as_of": "2025-1-01"}),
        ("list_13f_filings", {"cik": int(first), "as_of": "2025-01-01"}),
        ("list_13f_filings", {"cik": first, "as_of": "2025-01-01", "extra": True}),
        ("get_holdings_as_of", {"cik": first, "period": "2024-12-30", "as_of": "2025-08-27"}),
        ("get_holdings_as_of", {"cik": first, "period": "2024-12-31", "as_of": "2025-08-27",
                                "position_type": "short"}),
        ("get_holdings_as_of", {"cik": first, "period": "2024-12-31", "as_of": "2025-08-27",
                                "position_type": "long"}),
        ("get_holdings_as_of", {"cik": first, "period": "2024-12-31", "as_of": "2025-08-27", "cusip": "037833100"}),
        ("get_holdings_as_of", {"cik": first, "period": "2024-12-31", "as_of": "2025-08-27", "cusip": []}),
        ("get_holdings_as_of", {"cik": first, "period": "2026-03-31", "as_of": "2025-08-27"}),
        ("diff_holdings", {"cik": first, "period_a": "2024-12-31", "period_b": "2024-09-30", "as_of": "2025-08-27"}),
        ("diff_holdings", {"cik": first, "period_a": "2024-12-31", "period_b": "2026-03-31", "as_of": "2025-08-27"}),
    ]:
        out.append((FIXTURES.name, tool, args))
    return out


def response_hash(source, tool: str, args: dict) -> str:
    from edgar13f import server

    res = server.result_for(source, tool, args)
    text = res.content[0].text
    return hashlib.sha256(f"{bool(res.is_error)}|{text}".encode()).hexdigest()[:16]


def grid_digest(items: list[tuple[str, str, dict]]) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()


def compute(items: list[tuple[str, str, dict]]) -> list[str]:
    from edgar13f.sources import FixtureSource

    sources = {FIXTURES.name: FixtureSource(FIXTURES), "synthetic": FixtureSource(FIXTURES / "synthetic")}
    return [response_hash(sources[tag], tool, args) for tag, tool, args in items]


def main() -> None:
    import edgar13f

    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--label", required=True, help="which source wrote it, e.g. a tag")
    a = p.parse_args()
    items = grid()
    print(f"edgar13f {edgar13f.__version__} from {Path(edgar13f.__file__).parent}")
    report = {"written_by": a.label,
              "hash": "sha256(f'{isError}|{first text block}')[:16]", "calls": len(items),
              "grid_sha256": grid_digest(items), "responses": compute(items)}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=0) + "\n")
    print(f"{len(items)} calls -> {a.out}")


if __name__ == "__main__":
    main()
