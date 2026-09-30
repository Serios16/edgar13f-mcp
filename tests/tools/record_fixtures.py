"""Record offline fixtures from live EDGAR (NOT run in CI; needs network + SEC_USER_AGENT).

Usage: python tests/tools/record_fixtures.py <record_as_of> <cik> [<cik> ...]

Writes tests/fixtures/<cik>/filings.json and rows/<accession>.json for 13F-HR /
13F-HR/A filings whose period is within ROW_PERIODS. Rows come from
EdgarSource.rows, i.e. they are blocklist-redacted at parse time; this script
re-checks every row against the blocklist and aborts (printing no row data) if
anything slipped through.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from edgar13f import blocklist, config
from edgar13f.rules import HOLDINGS_FORMS
from edgar13f.sec_client import SecClient
from edgar13f.sources import EdgarSource

ROOT = Path(__file__).resolve().parents[1] / "fixtures"
ROW_PERIODS = ("2023-09-30", "2025-09-30")


def main(record_as_of: str, ciks: list[str]) -> None:
    cache = config.cache_dir()
    src = EdgarSource(SecClient(cache, config.user_agent()), cache)
    for raw in ciks:
        cik = str(int(raw))
        filings = src.filings(cik, record_as_of)
        if filings is None:
            print(f"{cik}: unknown CIK, skipped")
            continue
        out = ROOT / cik
        (out / "rows").mkdir(parents=True, exist_ok=True)
        meta = {"cik": cik, "recorded_as_of": record_as_of, "filings": [f.to_json() for f in filings]}
        (out / "filings.json").write_text(json.dumps(meta, indent=0, sort_keys=True) + "\n")
        n_rows = 0
        for f in filings:
            period = f.period_of_report or ""
            if f.form_type not in HOLDINGS_FORMS or not ROW_PERIODS[0] <= period <= ROW_PERIODS[1]:
                continue
            rows = src.rows(f)
            if any(blocklist.is_blocked(r["name_of_issuer"], r["title_of_class"], r["cusip"]) for r in rows):
                sys.exit(f"{cik}: blocklisted row survived redaction; aborting without writing")
            text = "[\n" + ",\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n]\n"
            (out / "rows" / f"{f.accession_number}.json").write_text(text)
            n_rows += len(rows)
        print(f"{cik}: {len(filings)} filings, {n_rows} rows")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
