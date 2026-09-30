"""Write the synthetic §4 fixture manager to tests/fixtures/synthetic/ (offline, deterministic).

Usage: python tests/tools/make_synthetic_fixtures.py

One invented manager (CIK 9900000001, beyond any real EDGAR CIK) whose periods
each exercise one CONTRACTS §4 case that recorded data lacks or has too few of.
Issuers, CUSIPs and numbers are invented; every row is benign (no blocklist
match). Blocklist-in-restatement cases are built in memory by the tests, never
stored as fixtures (hard rule 2).
"""

from __future__ import annotations

import json
from pathlib import Path

CIK = "9900000001"
OUT = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic" / CIK
SEC = {  # key -> (name_of_issuer, title_of_class, cusip as filed in ORIGINALs)
    "A": ("SYNTH ALPHA INC", "COM", "90000A101"),
    "B": ("SYNTH BETA CORP", "COM", "90000B102"),
    "C": ("SYNTH GAMMA CO", "CL A", "900000103"),
    "D": ("SYNTH DELTA LTD", "COM", "90000D104"),
    "E": ("SYNTH EPSILON INC", "COM", "90000E105"),
}

# (accession suffix, form, filing_date, period, amendment_no, amendment_type, rows)
# rows: (security key, shares, put_call, cusip override as filed)
FILINGS = [
    # 2024-03-31: zero-row RESTATEMENT supersedes a 3-row ORIGINAL.
    ("24-000001", "13F-HR", "2024-05-10", "2024-03-31", None, None, [("A", 100, None), ("B", 200, None), ("C", 300, None)]),
    ("24-000002", "13F-HR/A", "2024-05-20", "2024-03-31", 1, "RESTATEMENT", []),
    # 2024-06-30: three amendments on one day; amendment_no order disagrees with accession order.
    ("24-000003", "13F-HR", "2024-08-09", "2024-06-30", None, None, [("A", 110, None), ("B", 210, None)]),
    ("24-000005", "13F-HR/A", "2024-08-20", "2024-06-30", 1, "NEW HOLDINGS", [("D", 400, None)]),
    ("24-000004", "13F-HR/A", "2024-08-20", "2024-06-30", 2, "RESTATEMENT", [("A", 111, None), ("B", 211, None), ("C", 311, None)]),
    ("24-000006", "13F-HR/A", "2024-08-20", "2024-06-30", 3, "NEW HOLDINGS", [("E", 500, None)]),
    # 2024-09-30: UNSPECIFIED amendment (no cover-page type), then NEW HOLDINGS.
    ("24-000007", "13F-HR", "2024-11-08", "2024-09-30", None, None, [("A", 120, None), ("B", 220, None)]),
    ("24-000008", "13F-HR/A", "2024-11-12", "2024-09-30", 1, None, [("A", 121, None), ("C", 321, None)]),
    ("24-000009", "13F-HR/A", "2024-11-20", "2024-09-30", 2, "NEW HOLDINGS", [("D", 421, None)]),
    # 2024-12-31: RESTATEMENT after NEW HOLDINGS, then another NEW HOLDINGS.
    ("25-000001", "13F-HR", "2025-02-10", "2024-12-31", None, None, [("A", 130, None), ("B", 230, None)]),
    ("25-000002", "13F-HR/A", "2025-02-20", "2024-12-31", 1, "NEW HOLDINGS", [("C", 330, None)]),
    ("25-000003", "13F-HR/A", "2025-03-05", "2024-12-31", 2, "RESTATEMENT", [("A", 131, None), ("B", 231, None), ("C", 331, None)]),
    ("25-000004", "13F-HR/A", "2025-03-15", "2024-12-31", 3, "NEW HOLDINGS", [("D", 431, None)]),
    # 2025-03-31: RESTATEMENT filed with lowercase CUSIP letters (and one mixed-case duplicate).
    ("25-000005", "13F-HR", "2025-05-09", "2025-03-31", None, None, [("A", 140, None), ("B", 240, None), ("C", 340, None)]),
    ("25-000006", "13F-HR/A", "2025-05-20", "2025-03-31", 1, "RESTATEMENT",
     [("A", 141, None, "90000a101"), ("A", 9, None, "90000A101"), ("A", 5, "PUT", "90000a101"),
      ("B", 231, None, "90000b102"), ("D", 441, None, "90000d104")]),
    # 2025-06-30: only a notice and a notice restatement are visible.
    ("25-000007", "13F-NT", "2025-08-10", "2025-06-30", None, None, None),
    ("25-000008", "13F-NT/A", "2025-08-12", "2025-06-30", 1, "RESTATEMENT", None),
]


def _row(acc: str, key: str, shares: int, put_call: str | None, cusip: str | None = None) -> dict:
    name, title, filed = SEC[key]
    return {
        "accession_number": acc, "name_of_issuer": name, "title_of_class": title, "cusip": cusip or filed,
        "figi": None, "value": shares * 10, "shares_or_principal_amount": shares, "sh_prn": "SH",
        "put_call": put_call, "investment_discretion": "SOLE", "other_manager": None,
        "voting_authority_sole": shares, "voting_authority_shared": 0, "voting_authority_none": 0,
    }


def main() -> None:
    (OUT / "rows").mkdir(parents=True, exist_ok=True)
    filings = []
    for suffix, form, date, period, no, kind, rows in FILINGS:
        acc = f"{CIK}-{suffix}"
        filings.append({
            "cik": CIK, "accession_number": acc, "form_type": form, "filing_date": date,
            "period_of_report": period, "amendment_no": no, "amendment_type": kind,
            "report_type": "13F NOTICE" if form.startswith("13F-NT") else "13F HOLDINGS REPORT",
            "filing_manager_name": "SYNTHETIC SECTION 4 MANAGER", "primary_doc": "primary_doc.xml",
        })
        if rows is not None:
            text = "[\n" + ",\n".join(json.dumps(_row(acc, *r), sort_keys=True) for r in rows) + "\n]\n"
            (OUT / "rows" / f"{acc}.json").write_text(text if rows else "[]\n")
    meta = {"cik": CIK, "recorded_as_of": "synthetic", "filings": filings}
    (OUT / "filings.json").write_text(json.dumps(meta, indent=0, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
