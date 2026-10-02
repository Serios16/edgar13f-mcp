"""Stage 3 (b): EdgarSource fetches only what the requested periods need, with the same answers.

Each recorded and synthetic fixture manager is turned into a small offline EDGAR: the
submissions JSON split into a "recent" block and older pages (newest first, with unrelated
filings between the 13Fs), and cover pages built from the recorded metadata. Information-table
rows are seeded into the rows cache, so no table is parsed here. Every golden-grid call on
that EDGAR must return the bytes v1.0.0 returned on the fixtures (`tests/golden/`).
"""

from __future__ import annotations

import json
import shutil
from xml.sax.saxutils import escape

import pytest

from edgar13f import server, tools
from edgar13f.rules import Filing
from edgar13f.sources import EdgarSource
from tests.conftest import FIXTURES, REPO
from tests.tools import fixture_golden as fg

GOLDEN = json.loads((REPO / "tests" / "golden" / "v1_0_fixture_responses.json").read_text())
LAYOUTS = {"tiny pages": (3, 2), "large pages": (12, 9)}  # (filings in "recent", filings per page)


def _mdy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{m}-{d}-{y}"


def _cover(f: dict) -> bytes:
    def el(tag, value):
        return f"<{tag}>{escape(str(value))}</{tag}>" if value is not None else ""

    period = _mdy(f["period_of_report"]) if f["period_of_report"] else None
    amend = f"<amendmentInfo>{el('amendmentType', f['amendment_type'])}</amendmentInfo>" if f["amendment_type"] else ""
    return (f'<?xml version="1.0"?><edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">'
            f"<headerData><filerInfo>{el('periodOfReport', period)}</filerInfo></headerData>"
            f"<formData><coverPage>{el('reportCalendarOrQuarter', period)}{el('amendmentNo', f['amendment_no'])}"
            f"{amend}<filingManager>{el('name', f['filing_manager_name'])}</filingManager>"
            f"{el('reportType', f['report_type'])}</coverPage></formData></edgarSubmission>").encode()


def _table(entries: list[dict]) -> dict:
    return {"accessionNumber": [e["accession_number"] for e in entries],
            "filingDate": [e["filing_date"] for e in entries],
            "reportDate": [e["period_of_report"] or "" for e in entries],
            "form": [e["form_type"] for e in entries],
            "primaryDocument": [e["primary_doc"] or "" for e in entries]}


class FakeEdgar:
    """The URLs EdgarSource asks for, answered from a list of filing dicts; records each URL."""

    def __init__(self, cik: str, filings: list[dict], recent: int, per_page: int):
        filler = [{"accession_number": f"0009999999-{i:02d}-{i:06d}", "form_type": "10-Q",
                   "filing_date": f["filing_date"], "period_of_report": None, "primary_doc": "doc.htm"}
                  for i, f in enumerate(filings)]
        entries = sorted(filings + filler, key=lambda e: (e["filing_date"], e["accession_number"]), reverse=True)
        older = [entries[i:i + per_page] for i in range(recent, len(entries), per_page)]
        files = []
        self.files: dict[str, bytes] = {}
        for n, chunk in enumerate(older, 1):
            name = f"CIK{int(cik):010d}-submissions-{n:03d}.json"
            files.append({"name": name, "filingCount": len(chunk), "filingFrom": chunk[-1]["filing_date"],
                          "filingTo": chunk[0]["filing_date"]})
            self.files[name] = json.dumps(_table(chunk)).encode()
        main = {"cik": cik, "filings": {"recent": _table(entries[:recent]), "files": files}}
        self.files[f"CIK{int(cik):010d}.json"] = json.dumps(main).encode()
        for f in filings:
            doc = (f["primary_doc"] or "").rsplit("/", 1)[-1]
            if doc.lower().endswith(".xml"):
                self.files[f"{f['accession_number'].replace('-', '')}/{doc}"] = _cover(f)
        self.asked: list[str] = []

    def get(self, url, store=True, fetched_after=None):
        self.asked.append(url)
        parts = url.split("/")
        return self.files.get(parts[-1]) or self.files.get("/".join(parts[-2:]))

    def covers(self) -> int:
        return sum(1 for u in self.asked if "/Archives/" in u)


def _source(tmp_path, root, cik: str, layout: str) -> tuple[EdgarSource, FakeEdgar]:
    filings = json.loads((root / cik / "filings.json").read_text())["filings"]
    fake = FakeEdgar(cik, filings, *LAYOUTS[layout])
    cache = tmp_path / layout / root.name / cik
    if (root / cik / "rows").exists():
        shutil.copytree(root / cik / "rows", cache / "rows")
    return EdgarSource(fake, cache), fake


def _by_manager():
    groups: dict[tuple, list[tuple[int, str, dict]]] = {}
    for i, (tag, tool, args) in enumerate(fg.grid()):
        if "cik" in args and isinstance(args["cik"], str) and args["cik"].isdigit():
            groups.setdefault((tag, args["cik"]), []).append((i, tool, args))
    return groups


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_edgar_source_on_every_fixture_manager_matches_v1_0(tmp_path, layout):
    roots = {FIXTURES.name: FIXTURES, "synthetic": FIXTURES / "synthetic"}
    checked = 0
    for (tag, cik), calls in _by_manager().items():
        if not (roots[tag] / cik / "filings.json").exists():
            continue  # the unknown-CIK cases
        src, _ = _source(tmp_path, roots[tag], cik, layout)
        bad = [i for i, tool, args in calls if fg.response_hash(src, tool, args) != GOLDEN["responses"][i]]
        assert bad == [], (tag, cik, len(bad))
        checked += len(calls)
    assert checked == 3686  # every golden call on a fixture manager


def test_holdings_fetch_far_fewer_covers_and_no_page_before_the_period(tmp_path):
    cik = "1067983"  # the fixture manager with the most filings
    src, fake = _source(tmp_path, FIXTURES, cik, "tiny pages")
    out = tools.call(src, "get_holdings_as_of", {"cik": cik, "period": "2025-03-31", "as_of": "2025-08-27"})
    assert out["status"] == "ok"
    holdings_covers, pages = fake.covers(), [u for u in fake.asked if "-submissions-" in u]
    meta = {json.loads(fake.files[u.rsplit("/", 1)[-1]])["filingDate"][0] for u in pages}  # newest date per page
    assert all(d >= "2025-03-31" for d in meta)
    fake.asked.clear()
    assert tools.call(src, "list_13f_filings", {"cik": cik, "as_of": "2025-08-27"})["status"] == "ok"
    assert holdings_covers <= 6 and fake.covers() >= 50  # 57 of its filings have an XML cover page


def _synthetic(cik: str, thirteen_f: list[tuple[str, str, str]]) -> list[dict]:
    """13F filings (form, filing_date, period) plus monthly unrelated filings 2019-2025."""
    out = [{"accession_number": f"0000000002-{d[2:4]}-{n:06d}", "form_type": form, "filing_date": d,
            "period_of_report": p, "primary_doc": "primary_doc.xml", "amendment_no": None,
            "amendment_type": None, "report_type": "13F HOLDINGS REPORT", "filing_manager_name": "SYNTH"}
           for n, (form, d, p) in enumerate(thirteen_f, 1)]
    out += [{"accession_number": f"0000000003-{y % 100:02d}-{m:06d}", "form_type": "8-K",
             "filing_date": f"{y}-{m:02d}-15", "period_of_report": None, "primary_doc": "x.htm"}
            for y in range(2019, 2026) for m in range(1, 13)]
    return out


@pytest.mark.parametrize("thirteen_f, period, as_of, want", [
    ([("13F-HR", "2019-02-14", "2018-12-31")], "2025-03-31", "2025-08-27", "not_yet_filed"),
    ([], "2025-03-31", "2025-08-27", "unknown_cik"),
    ([("13F-HR", "2025-05-15", "2025-03-31")], "2024-12-31", "2025-04-01", "unknown_cik"),
    ([("13F-NT", "2019-02-14", "2018-12-31"), ("13F-NT", "2025-05-15", "2025-03-31")],
     "2025-03-31", "2025-08-27", "notice_only"),
])
def test_unknown_cik_still_reads_older_pages_until_a_13f_is_found(tmp_path, thirteen_f, period, as_of, want):
    fake = FakeEdgar("2", [f for f in _synthetic("2", thirteen_f) if f["form_type"] != "8-K"]
                     + [f for f in _synthetic("2", []) if f["form_type"] == "8-K"], 5, 6)
    src = EdgarSource(fake, tmp_path)
    out = tools.call(src, "get_holdings_as_of", {"cik": "2", "period": period, "as_of": as_of})
    assert out.get("reason") == want
    pages = [u for u in fake.asked if "-submissions-" in u]
    if want == "unknown_cik":  # every page dated on or before as_of was read
        total = json.loads(fake.files["CIK0000000002.json"])["filings"]["files"]
        assert len(pages) == sum(1 for p in total if p["filingFrom"] <= as_of)


EARLY = [("13F-HR", "2025-05-15", "2025-06-30")]  # a report dated before its own period end
EARLY_ARGS = {"cik": "2", "period": "2025-06-30", "as_of": "2025-05-20"}


def test_report_filed_before_its_period_is_seen_when_its_page_is_read(tmp_path):
    # Its index period is the requested one, so its cover is read although it is dated earlier.
    fake = FakeEdgar("2", _synthetic("2", EARLY), 40, 6)
    out = tools.call(EdgarSource(fake, tmp_path), "get_holdings_as_of", EARLY_ARGS)
    assert out["status"] == "ok" and out["source_accessions"] == ["0000000002-25-000001"]


def test_documented_limit_report_filed_before_its_period_in_an_older_page(tmp_path):
    # REGISTER A17: a page that ends before the requested period is not read once a 13F is
    # visible elsewhere, so such a report is missed there (v1.0 read every page).
    filings = _synthetic("2", EARLY + [("13F-HR", "2025-08-01", "2025-03-31")])
    fake = FakeEdgar("2", filings, 3, 6)
    assert fake.files["CIK0000000002.json"]  # recent: the three newest filings only
    out = tools.call(EdgarSource(fake, tmp_path), "get_holdings_as_of", {**EARLY_ARGS, "as_of": "2025-08-27"})
    assert out.get("reason") == "not_yet_filed"


def test_filing_record_fields_unchanged_for_list(tmp_path):
    root, cik = FIXTURES, "1894571"
    src, _ = _source(tmp_path, root, cik, "tiny pages")
    want = [Filing(**f).record() for f in json.loads((root / cik / "filings.json").read_text())["filings"]
            if f["filing_date"] <= "2025-08-27"]
    got = server.result_for(src, "list_13f_filings", {"cik": cik, "as_of": "2025-08-27"}).structured_content
    assert sorted(got["filings"], key=lambda r: r["accession_number"]) == \
        sorted(want, key=lambda r: r["accession_number"])
