"""Data sources: live EDGAR (with on-disk cache) and recorded fixtures.

Both expose:
  filings(cik, as_of[, periods]) -> list[Filing] | None   (None: CIK does not exist)
  rows(filing)        -> list[dict]            (information-table rows, blocklist applied)
Visibility (§3) is enforced by the tools via `rules.visible`; EdgarSource also
uses it to avoid fetching anything about filings that are not visible.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import blocklist, managers, parse, rules
from .config import write_json as _write_json
from .rules import Filing
from .sec_client import SecClient

DATA = "https://data.sec.gov/submissions"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"


def _freshness(as_of: str) -> float:
    """Cached submissions JSON is valid for `as_of` only if fetched >= 2 days after it."""
    day = dt.date.fromisoformat(as_of) + dt.timedelta(days=2)
    return dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc).timestamp()


class EdgarSource:
    def __init__(self, client: SecClient, cache: Path) -> None:
        self.client = client
        self.redact = blocklist.redacting()
        self.rows_dir = cache / ("rows" if self.redact else "rows-unredacted")
        self.directory = managers.EdgarDirectory(client, cache)

    def _folder(self, f: Filing) -> str:
        return f"{ARCHIVES}/{f.cik}/{f.accession_number.replace('-', '')}"

    def filings(self, cik: str, as_of: str, periods: tuple[str, ...] | None = None) -> list[Filing] | None:
        """Visible 13F filings. With `periods`, only what can bear on those report periods is
        fetched: a report for period P is filed on or after P, so older submission pages that end
        before the earliest period are read only while no visible 13F has been found (unknown_cik),
        and cover pages only for filings dated on or after it, or whose index period is blank or
        one of `periods`. The other filings keep their index metadata."""
        fresh = _freshness(as_of)
        body = self.client.get(f"{DATA}/CIK{int(cik):010d}.json", fetched_after=fresh)
        if body is None:
            return None
        data = json.loads(body).get("filings", {})
        lo = min(periods) if periods else ""
        pages = [p for p in data.get("files", []) if p.get("filingFrom", "") <= as_of]
        near = [p for p in pages if (p.get("filingTo") or as_of) >= lo]
        out: dict[str, Filing] = {}
        for t in [data.get("recent", {})] + [self._page(p) for p in near]:
            self._collect(t, cik, as_of, out)
        far = sorted((p for p in pages if p not in near), key=lambda p: p.get("filingTo", ""), reverse=True)
        for p in far:
            if out:
                break
            self._collect(self._page(p), cik, as_of, out)
        return [self._enrich(f) if not periods or f.filing_date >= lo or not f.period_of_report
                or f.period_of_report in periods else f for f in out.values()]

    def _page(self, page: dict) -> dict:
        extra = self.client.get(f"{DATA}/{page['name']}")
        return json.loads(extra) if extra is not None else {}

    @staticmethod
    def _collect(t: dict, cik: str, as_of: str, out: dict[str, Filing]) -> None:
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
                out[f.accession_number] = f

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
                rows.extend(parse.parse_infotable(body, f.accession_number, self.redact))
            del body
        if not found:
            # A document named e.g. index.xml is shadowed by EDGAR's own directory listing at
            # that URL; the full submission text still carries every document.
            body = self.client.get(f"{self._folder(f)}/{f.accession_number}.txt", store=False)
            for xml in parse.submission_xml(body or b""):
                if parse.is_infotable(xml):
                    rows.extend(parse.parse_infotable(xml, f.accession_number, self.redact))
            del body
        _write_json(path, rows)
        return rows


class FixtureSource:
    """Recorded, blocklist-redacted fixtures: <dir>/<cik>/filings.json, rows/<acc>.json."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.directory = FixtureDirectory(root)

    def filings(self, cik: str, as_of: str, periods: tuple[str, ...] | None = None) -> list[Filing] | None:
        path = self.root / cik / "filings.json"
        if not path.exists():
            return None
        return [Filing(**rec) for rec in json.loads(path.read_text())["filings"]]

    def rows(self, f: Filing) -> list[dict]:
        path = self.root / f.cik / "rows" / f"{f.accession_number}.json"
        if not path.exists():
            raise LookupError(f"fixture rows missing for {f.accession_number}")
        return json.loads(path.read_text())


class FixtureDirectory:
    """find_manager over fixtures: a manager's names are its cover-page names (upper case), its
    current name the latest of them, and its 13F dates those in filings.json."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _filings(self, cik: str = "*") -> dict[str, list[dict]]:
        return {p.parent.name: [f for f in json.loads(p.read_text())["filings"] if f["form_type"] in rules.ALL_FORMS]
                for p in sorted(self.root.glob(f"{cik}/filings.json"))}

    def search(self, name: str) -> dict[str, tuple[str, ...]]:
        out = {}
        for cik, fs in self._filings().items():
            names = tuple(sorted({f["filing_manager_name"].upper() for f in fs if f["filing_manager_name"]}))
            if any(name.upper() in n for n in names):
                out[cik] = names
        return out

    def first_13f(self, as_of: str | None) -> dict[str, str]:
        return {cik: min(f["filing_date"] for f in fs) for cik, fs in self._filings().items() if fs}

    def current_name(self, cik: str) -> str | None:
        named = [f for f in self._filings(cik).get(cik, []) if f["filing_manager_name"]]
        return max(named, key=lambda f: (f["filing_date"], f["accession_number"]))["filing_manager_name"] if named else None
