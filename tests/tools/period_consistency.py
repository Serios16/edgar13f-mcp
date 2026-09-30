"""Compare cover-page period vs header periodOfReport vs submissions reportDate for fixture
filers (uses the on-disk cache; fetches anything missing). Not run in CI."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

from edgar13f import config, parse
from edgar13f.sec_client import SecClient
from edgar13f.sources import ARCHIVES, DATA

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def main() -> None:
    cache = config.cache_dir()
    client = SecClient(cache, config.user_agent())
    tally: Counter = Counter()
    for d in sorted(p for p in FIX.iterdir() if p.is_dir()):
        sub = json.loads(client.get(f"{DATA}/CIK{int(d.name):010d}.json"))["filings"]["recent"]
        report_date = dict(zip(sub["accessionNumber"], sub["reportDate"]))
        for f in json.loads((d / "filings.json").read_text())["filings"]:
            if not (f["primary_doc"] or "").endswith(".xml") or f["accession_number"] not in report_date:
                continue
            acc = f["accession_number"]
            xml = client.get(f"{ARCHIVES}/{d.name}/{acc.replace('-', '')}/{f['primary_doc'].rsplit('/', 1)[-1]}")
            cover = parse.parse_cover(xml)["period_of_report"]
            tally["compared"] += 1
            tally["cover==reportDate" if cover == report_date[acc] else "cover!=reportDate"] += 1
    print(json.dumps(tally, indent=1))


if __name__ == "__main__":
    sys.exit(main())
