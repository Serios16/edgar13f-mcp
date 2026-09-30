"""Data sources: live EDGAR (with on-disk cache) and recorded fixtures.

Both expose:
  filings(cik, as_of) -> list[Filing] | None   (None: CIK does not exist)
  rows(filing)        -> list[dict]            (information-table rows, blocklist applied)
Visibility (§3) is enforced by the tools via `rules.visible`; EdgarSource also
uses it to avoid fetching anything about filings that are not visible.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from . import parse, rules
from .rules import Filing
from .sec_client import SecClient

DATA = "https://data.sec.gov/submissions"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"


def _freshness(as_of: str) -> float:
    """Cached submissions JSON is valid for `as_of` only if fetched >= 2 days after it."""
    day = dt.date.fromisoformat(as_of) + dt.timedelta(days=2)
    return dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc).timestamp()


def _write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj))
    tmp.replace(path)


class EdgarSource:
    def __init__(self, client: SecClient, cache: Path) -> None:
        self.client = client
        self.rows_dir = cache / "rows"

    def _folder(self, f: Filing) -> str:
        return f"{ARCHIVES}/{f.cik}/{f.accession_number.replace('-', '')}"

    def filings(self, cik: str, as_of: str) -> list[Filing] | None:
        fresh = _freshness(as_of)
        body = self.client.get(f"{DATA}/CIK{int(cik):010d}.json", fetched_after=fresh)
        if body is None:
            return None
        data = json.loads(body).get("filings", {})
        tables = [data.get("recent", {})]
        for page in data.get("files", []):
            if page.get("filingFrom", "") <= as_of:
                extra = self.client.get(f"{DATA}/{page['name']}")
                if extra is not None:
                    tables.append(json.loads(extra))
        out: dict[str, Filing] = {}
        for t in tables:
            for i, form in enumerate(t.get("form", [])):
                if form not in rules.ALL_FORMS:
                    continue
                f = Filing(
                    cik=cik,
                    accession_number=t["accessionNumber"][i],
                    form_type=form,
                    filing_date=t["filingDate"][i],
                    period_of_report=t["reportDate"][i] or None,
                    primary_doc=(t.get("primaryDocument") or [""] * (i + 1))[i] or None,
                )
                if rules.visible(f, as_of) and f.accession_number not in out:
                    out[f.accession_number] = self._enrich(f)
        return list(out.values())

    def _enrich(self, f: Filing) -> Filing:
        """Add cover-page metadata (amendment no/type, report type, manager name)."""
        if not f.primary_doc or not f.primary_doc.lower().endswith(".xml"):
            return f
        body = self.client.get(f"{self._folder(f)}/{f.primary_doc.rsplit('/', 1)[-1]}")
        if body is None:
            return f
        cover = parse.parse_cover(body)
        cover["period_of_report"] = cover["period_of_report"] or f.period_of_report
        return Filing(**{**f.to_json(), **cover})

    def rows(self, f: Filing) -> list[dict]:
        path = self.rows_dir / f"{f.accession_number}.json"
        if path.exists():
            return json.loads(path.read_text())
        index = self.client.get(f"{self._folder(f)}/index.json")
        items = json.loads(index)["directory"]["item"] if index else []
        primary = (f.primary_doc or "").rsplit("/", 1)[-1]
        rows: list[dict] = []
        found = False
        for item in items:
            name = item.get("name", "")
            if not name.lower().endswith(".xml") or name == primary:
                continue
            body = self.client.get(f"{self._folder(f)}/{name}", store=False)
            if body is not None and parse.is_infotable(body):
                found = True
                rows.extend(parse.parse_infotable(body, f.accession_number))
            del body
        if not found:
            # A document named e.g. index.xml is shadowed by EDGAR's own directory listing at
            # that URL; the full submission text still carries every document.
            body = self.client.get(f"{self._folder(f)}/{f.accession_number}.txt", store=False)
            for xml in parse.submission_xml(body or b""):
                if parse.is_infotable(xml):
                    rows.extend(parse.parse_infotable(xml, f.accession_number))
            del body
        _write_json(path, rows)
        return rows


class FixtureSource:
    """Recorded, blocklist-redacted fixtures: <dir>/<cik>/filings.json, rows/<acc>.json."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def filings(self, cik: str, as_of: str) -> list[Filing] | None:
        path = self.root / cik / "filings.json"
        if not path.exists():
            return None
        return [Filing(**rec) for rec in json.loads(path.read_text())["filings"]]

    def rows(self, f: Filing) -> list[dict]:
        path = self.root / f.cik / "rows" / f"{f.accession_number}.json"
        if not path.exists():
            raise LookupError(f"fixture rows missing for {f.accession_number}")
        return json.loads(path.read_text())
