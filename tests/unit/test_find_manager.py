"""Addendum A4 find_manager: ordering, has_13f_filings as of a date, declines, and the EDGAR
directory (CIK lookup names, quarterly form-index prefixes, current names) on a fake client.
Every entity below is invented."""

from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import time

import pytest

from edgar13f import DISCLAIMER, managers, tools
from edgar13f.sec_client import SecClient
from tests.conftest import FIXTURES

# cik: (every EDGAR name, current name, earliest 13F filing date or None)
ENTITIES = {
    "11": (("NORTHWIND CAPITAL LLC",), "Northwind Capital LLC", "2020-02-14"),
    "12": (("NORTHWIND CAPITAL TRUST",), "NORTHWIND CAPITAL TRUST", None),
    "13": (("AAA NORTHWIND OLD NAME", "ZEBRA HOLDINGS NORTHWIND"), "Zebra Holdings Northwind", "2024-05-15"),
    "14": (("NORTHWIND PARTNERS",), "Northwind Partners", "2025-08-14"),
    "15": (("ALPHA NORTHWIND FUND",), "Alpha Northwind Fund", None),
    "16": (("NORTHWIND GOLD TRUST",), "Northwind Gold Trust", "2010-01-04"),  # matches the blocklist
    "17": (("BETA NORTHWIND ADVISORS",), "Beta Northwind Advisors", "2001-05-15"),
    "18": (("OTHER NAME ENTIRELY",), "Other Name Entirely", "2001-05-15"),
}


class Directory:
    def __init__(self, entities=ENTITIES):
        self.entities, self.resolved = entities, []

    def search(self, name):
        return {c: e[0] for c, e in self.entities.items() if any(name.upper() in n for n in e[0])}

    def first_13f(self, as_of):
        return {c: e[2] for c, e in self.entities.items() if e[2]}

    def current_name(self, cik):
        self.resolved.append(cik)
        return self.entities[cik][1]


class Src:
    def __init__(self, entities=ENTITIES):
        self.directory = Directory(entities)


def find(src=None, **args):
    out = tools.call(src or Src(), "find_manager", args)
    assert out["disclaimer"] == DISCLAIMER
    json.dumps(out)
    return out


def ciks(out):
    return [(c["cik"], c["has_13f_filings"]) for c in out["candidates"]]


def test_filers_first_then_by_current_name():
    out = find(name="northwind")
    assert ciks(out) == [("17", True), ("11", True), ("14", True), ("13", True), ("15", False), ("12", False)]
    assert [c["entity_name"] for c in out["candidates"]][:4] == [
        "Beta Northwind Advisors", "Northwind Capital LLC", "Northwind Partners", "Zebra Holdings Northwind"]
    assert list(out) == ["status", "disclaimer", "query", "candidates", "note"]
    assert out["query"] == "northwind" and "current name" in out["note"] and "not point-in-time" in out["note"]


@pytest.mark.parametrize("as_of, want", [
    ("2025-08-13", [("17", True), ("11", True), ("13", True), ("15", False), ("12", False), ("14", False)]),
    ("2025-08-14", [("17", True), ("11", True), ("14", True), ("13", True), ("15", False), ("12", False)]),
    ("2024-05-14", [("17", True), ("11", True), ("15", False), ("12", False), ("14", False), ("13", False)]),
    ("2024-05-15", [("17", True), ("11", True), ("13", True), ("15", False), ("12", False), ("14", False)]),
    ("2001-05-14", [("15", False), ("17", False), ("11", False), ("12", False), ("14", False), ("13", False)]),
])
def test_has_13f_filings_counts_only_filings_on_or_before_as_of(as_of, want):
    out = find(name="Northwind", as_of=as_of)
    assert ciks(out) == want
    assert "on or before as_of" in out["note"]


def test_limit_default_range_and_laziness():
    assert len(find(name="northwind")["candidates"]) == 6
    many = {str(100 + i): ((f"NORTHWIND FILER {i:03d}",), f"Northwind Filer {i:03d}", "2020-01-02") for i in range(150)}
    src = Src({**ENTITIES, **many})
    out = find(src, name="northwind", limit=3)
    assert ciks(out) == [("17", True), ("11", True), ("100", True)]
    assert len(src.directory.resolved) <= 4  # only candidates that reach the answer (+ the renamed one)
    assert len(find(Src({**ENTITIES, **many}), name="northwind", limit=20)["candidates"]) == 20
    assert len(find(Src(many), name="filer")["candidates"]) == 10


def test_ties_on_name_order_by_cik():
    same = {"7": (("SAME NAME LLC",), "Same Name LLC", None), "5": (("SAME NAME LLC",), "Same Name LLC", None)}
    assert ciks(find(Src(same), name="same name")) == [("5", False), ("7", False)]


def test_no_match_is_an_empty_ok_answer():
    out = find(name="no such entity")
    assert out["status"] == "ok" and out["candidates"] == []


def test_blocklisted_entity_names_are_left_out():
    out = find(name="northwind gold")
    assert out["candidates"] == []
    assert "16" not in [c["cik"] for c in find(name="northwind")["candidates"]]


def test_renamed_entity_sorts_under_its_current_name():
    out = find(name="old name")  # matches only a former name
    assert out["candidates"] == [{"cik": "13", "entity_name": "Zebra Holdings Northwind", "has_13f_filings": True}]


@pytest.mark.parametrize("args", [
    {"name": "ab"}, {"name": "x" * 101}, {"name": 123}, {"name": None}, {}, {"name": "abc", "cik": "1"},
    {"name": "abc", "as_of": "2025-02-30"}, {"name": "abc", "as_of": "20250101"}, {"name": "abc", "as_of": None},
    {"name": "abc", "limit": 0}, {"name": "abc", "limit": 21}, {"name": "abc", "limit": True},
    {"name": "abc", "limit": "5"}, {"name": "abc", "limit": 2.0}, {"name": "abc", "period": "2025-03-31"},
])
def test_declines_are_invalid_argument(args):
    out = tools.call(Src(), "find_manager", args)
    assert out["status"] == "declined" and out["reason"] == "invalid_argument" and out["disclaimer"] == DISCLAIMER


def test_boundaries_accepted():
    assert find(name="abc", limit=1)["status"] == "ok"
    assert find(name="a" * 100, limit=20)["status"] == "ok"


def test_fixture_directory_agrees_with_list_13f_filings(fixture_source):
    """has_13f_filings(as_of) is true exactly when list_13f_filings(cik, as_of) is not unknown_cik."""
    checked = 0
    for path in sorted(FIXTURES.glob("*/filings.json")):
        cik, filings = path.parent.name, json.loads(path.read_text())["filings"]
        names = [f["filing_manager_name"] for f in filings if f["filing_manager_name"]]
        if not names:
            continue
        first = min(f["filing_date"] for f in filings)
        day = dt.date.fromisoformat(first)
        for as_of in {(day + dt.timedelta(days=d)).isoformat() for d in (-1, 0, 1)} | {"2025-08-27"}:
            out = find(fixture_source, name=names[0], as_of=as_of, limit=20)
            mine = [c for c in out["candidates"] if c["cik"] == cik]
            listed = tools.call(fixture_source, "list_13f_filings", {"cik": cik, "as_of": as_of})
            assert mine and mine[0]["has_13f_filings"] == (listed["status"] == "ok"), (cik, as_of)
            checked += 1
    assert checked >= 80


# EdgarDirectory on a fake SEC client

NAMES = "\n".join(sorted(f"{n}:{int(c):010d}:" for c, e in ENTITIES.items() for n in e[0]))
COLS = "{:<17}{:<62}{:<12}{:<12}{}"


def _idx(lines: list[tuple[str, str, str, str]], filler: int = 3000) -> bytes:
    """A form.idx in EDGAR's layout, sorted by form type, with filler before and after."""
    head = ("Description:           Master Index of EDGAR Dissemination Feed by Form Type\n"
            "Last Data Received:    Invented\n\n\n"
            + COLS.format("Form Type", "Company Name", "CIK", "Date Filed", "File Name") + "\n" + "-" * 140 + "\n")
    rows = [("10-K", f"FILLER {i}", str(900000 + i), "2026-01-05") for i in range(filler)]
    rows += lines + [("13FCONP", "X CO", "5", "2026-01-05"), ("13H", "Y CO", "6", "2026-01-05")]
    rows += [("8-K", f"LATER {i}", str(800000 + i), "2026-01-06") for i in range(filler)]
    rows.sort(key=lambda r: r[0])
    body = "".join(COLS.format(f, n, c, d, f"edgar/data/{c}/0000000000-26-{i:06d}.txt") + "\n"
                   for i, (f, n, c, d) in enumerate(rows))
    return (head + body).encode()


BLOCK = [("13F-E", "OLD STYLE", "18", "2026-01-02"), ("13F-HR", "NORTHWIND CAPITAL LLC", "11", "2026-02-14"),
         ("13F-HR", "NORTHWIND CAPITAL LLC", "11", "2026-01-30"), ("13F-HR/A", "ZEBRA  HOLDINGS", "13", "2026-03-01"),
         ("13F-NT", "BETA NORTHWIND ADVISORS", "17", "2026-02-10"), ("13F-NT/A", "NORTHWIND PARTNERS", "14", "2026-03-30")]


class FakeSec:
    """Answers the URLs EdgarDirectory asks for; honours Range like sec.gov (206 + slice)."""

    def __init__(self, gz: bytes, names: str = NAMES):
        self.gz, self.names, self.calls, self.ignore_range = gz, names.encode(), [], False

    def __call__(self, req, timeout):
        url, rng = req.full_url, req.get_header("Range")
        self.calls.append((url, rng))
        if url == managers.NAMES_URL:
            return 200, self.names, {}
        if "/full-index/" in url and self.ignore_range:
            return 200, self.gz, {}
        if "/full-index/" in url:
            lo, hi = (int(x) for x in rng.removeprefix("bytes=").split("-"))
            return 206, self.gz[lo:hi + 1], {}
        cik = str(int(url.rsplit("CIK", 1)[1].split(".")[0]))
        if cik in ENTITIES:
            return 200, json.dumps({"cik": cik, "name": ENTITIES[cik][1]}).encode(), {}
        return 404, b"", {}


def _directory(tmp_path, monkeypatch, gz=None, first_year=None, rng=1 << 20):
    gz = gz if gz is not None else gzip.compress(_idx(BLOCK))
    fake = FakeSec(gz)
    monkeypatch.setattr(managers, "FIRST_YEAR", first_year or dt.datetime.now(dt.timezone.utc).year)
    monkeypatch.setattr(managers, "RANGE", rng)
    client = SecClient(tmp_path, "tests test@example.com", opener=fake, sleep=lambda s: None)
    monkeypatch.setattr("edgar13f.sec_client.MIN_INTERVAL", 0.0)
    return managers.EdgarDirectory(client, tmp_path), fake


def test_index_block_reads_only_the_four_13f_forms_and_knows_when_it_is_complete():
    text = _idx(BLOCK)
    first, done = managers.index_block(text)
    assert done and first == {"11": "2026-01-30", "13": "2026-03-01", "17": "2026-02-10", "14": "2026-03-30"}
    cut = text[:text.index(b"13F-NT/A")]
    assert managers.index_block(cut) == ({"11": "2026-01-30", "13": "2026-03-01", "17": "2026-02-10"}, False)
    assert managers.index_block(text[:text.index(b"13F-E")]) == ({}, False)
    assert managers.index_block(text[:200]) == ({}, False)  # header only
    assert managers.index_block(_idx([], filler=5)) == ({}, True)


def test_first_13f_fetches_prefixes_with_range_and_caches_per_quarter(tmp_path, monkeypatch):
    gz = gzip.compress(_idx(BLOCK))
    d, fake = _directory(tmp_path, monkeypatch, gz, rng=4096)
    first = d.first_13f(None)
    assert first == {"11": "2026-01-30", "13": "2026-03-01", "17": "2026-02-10", "14": "2026-03-30"}
    idx = [(u, r) for u, r in fake.calls if "/full-index/" in u]
    quarters = {u for u, _ in idx}
    assert len(quarters) == (dt.datetime.now(dt.timezone.utc).month - 1) // 3 + 1
    per = [r for u, r in idx if u == min(quarters)]
    assert per[0] == "bytes=0-4095" and len(per) >= 2  # a 4 KiB prefix is not enough here: doubled ranges
    assert int(per[-1].split("-")[1]) < len(gz)  # stopped before the end of the file
    assert not any(p.name.startswith("tmp") for p in (tmp_path / "http").iterdir())
    assert len(list((tmp_path / "http").iterdir())) == 0  # byte ranges are never cached
    fake.calls.clear()
    assert d.first_13f(None) == first and fake.calls == []  # cached quarters, fresh enough


@pytest.mark.parametrize("ignore_range", [False, True])
def test_short_file_or_range_ignored_gives_the_whole_index(tmp_path, monkeypatch, ignore_range):
    d, fake = _directory(tmp_path, monkeypatch, gzip.compress(_idx(BLOCK, filler=10)), rng=64)
    fake.ignore_range = ignore_range
    assert d.first_13f(None)["14"] == "2026-03-30"


def test_stale_open_quarter_is_refetched_and_a_final_one_is_not(tmp_path, monkeypatch):
    d, fake = _directory(tmp_path, monkeypatch, first_year=dt.datetime.now(dt.timezone.utc).year - 1)
    d.first_13f(None)
    stale = set()
    for p in (tmp_path / "f13index").iterdir():
        y, q = int(p.stem[:4]), int(p.stem[-1])
        t = managers._ts(dt.date(y + q // 4, 3 * q % 12 + 1, 1) + dt.timedelta(days=1))  # end + 2 days: final
        if t > time.time():  # not over for two days yet: make the copy two days old (stale)
            t = time.time() - 2 * managers.DAY
            stale.add(f"/{y}/QTR{q}/")
        os.utime(p, (t, t))
    fake.calls.clear()
    d.first_13f(None)
    assert stale and {u.split("/full-index")[1][:11] for u, _ in fake.calls if "/full-index/" in u} == stale
    fake.calls.clear()
    d.first_13f("2001-01-01")  # nothing in the open quarter can be on or before as_of
    assert fake.calls == []


@pytest.mark.parametrize("mtime, as_of, want", [
    ("2025-04-02", None, True),          # fetched two days after the quarter ended: final
    ("2025-04-01", "2025-03-31", False),  # one day after: not final; as_of needs 2025-04-02
    ("2025-04-01", "2025-03-29", True),   # as_of + 2 days <= fetch time
    ("2025-01-15", "2024-12-31", True),   # as_of before the quarter: nothing in it can count
    ("2025-01-15", "2025-01-12", True),
    ("2025-01-15", "2025-01-14", False),
])
def test_quarter_freshness(mtime, as_of, want):
    m = managers._ts(dt.date.fromisoformat(mtime))
    assert managers._fresh(m, dt.date(2025, 1, 1), dt.date(2025, 3, 31), as_of) is want


def test_open_quarter_without_as_of_is_fresh_for_a_day():
    start, end = dt.date.today() - dt.timedelta(days=10), dt.date.today() + dt.timedelta(days=60)
    assert managers._fresh(time.time() - managers.DAY + 60, start, end, None)
    assert not managers._fresh(time.time() - managers.DAY - 60, start, end, None)


def test_search_matches_any_name_case_insensitively_and_returns_all_names(tmp_path, monkeypatch):
    d, fake = _directory(tmp_path, monkeypatch)
    assert d.search("old name") == {"13": ("AAA NORTHWIND OLD NAME", "ZEBRA HOLDINGS NORTHWIND")}
    assert set(d.search("Northwind")) == {"11", "12", "13", "14", "15", "16", "17"}
    assert d.search("LLC:00") == {} and d.search("0000000011") == {}  # names only, never the CIK field
    assert sum(1 for u, _ in fake.calls if u == managers.NAMES_URL) == 1


def test_find_manager_end_to_end_on_the_edgar_directory(tmp_path, monkeypatch):
    d, fake = _directory(tmp_path, monkeypatch)

    class Source:
        directory = d

    out = tools.call(Source(), "find_manager", {"name": "northwind", "as_of": "2026-02-12", "limit": 3})
    assert ciks(out) == [("17", True), ("11", True), ("15", False)]
    assert out["candidates"][1]["entity_name"] == "Northwind Capital LLC"  # current name, from submissions
    asked = [u for u, _ in fake.calls if "submissions" in u]
    assert len(asked) <= 4


def test_current_name_missing_falls_back_to_the_lookup_name(tmp_path, monkeypatch):
    d, fake = _directory(tmp_path, monkeypatch)
    fake.names = (NAMES + "\nNORTHWIND GHOST CO:0000000099:").encode()

    class Source:
        directory = d

    out = tools.call(Source(), "find_manager", {"name": "ghost"})
    assert out["candidates"] == [{"cik": "99", "entity_name": "NORTHWIND GHOST CO", "has_13f_filings": False}]


def test_concurrent_first_calls_build_the_index_once(tmp_path, monkeypatch):
    import threading

    d, fake = _directory(tmp_path, monkeypatch)
    threads = [threading.Thread(target=d.first_13f, args=(None,)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    urls = [u for u, _ in fake.calls if "/full-index/" in u]
    assert len(urls) == len(set(urls)) == (dt.datetime.now(dt.timezone.utc).month - 1) // 3 + 1


def test_missing_index_is_empty_only_for_a_quarter_not_yet_complete(tmp_path, monkeypatch):
    from edgar13f.sec_client import SecUnavailable

    d, fake = _directory(tmp_path, monkeypatch, first_year=dt.datetime.now(dt.timezone.utc).year - 1)
    today = dt.datetime.now(dt.timezone.utc).date()
    current = f"/{today.year}/QTR{(today.month - 1) // 3 + 1}/"
    real = fake.__call__

    def missing(where):
        def opener(req, timeout):
            if where in req.full_url:
                fake.calls.append((req.full_url, req.get_header("Range")))
                return 404, b"", {}
            return real(req, timeout)
        return opener

    d.client.opener = missing(current)
    assert d.first_13f(None)["14"] == "2026-03-30"  # the open quarter has no index yet: empty
    assert json.loads((tmp_path / "f13index" / f"{today.year}Q{(today.month - 1) // 3 + 1}.json").read_text()) == {}
    closed = tmp_path / "e2"
    d2, fake2 = _directory(closed, monkeypatch, first_year=today.year - 1)
    d2.client.opener = missing(f"/{today.year - 1}/QTR2/")
    with pytest.raises(SecUnavailable):  # a complete quarter must have an index: never cached as empty
        d2.first_13f(None)
    assert not (closed / "f13index" / f"{today.year - 1}Q2.json").exists()
