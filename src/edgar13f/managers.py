"""find_manager (Addendum A4): EDGAR entity names -> CIKs, with 13F status.

* Names: EDGAR's CIK lookup file, which lists every current and former name of every entity
  (upper case). The query is a case-insensitive substring of any of them. Refreshed daily.
* 13F status: the earliest 13F-HR, 13F-HR/A, 13F-NT or 13F-NT/A filing date of each CIK, from
  EDGAR's quarterly form indexes (full-index/YYYY/QTRn/form.gz, every quarter since 1993). Each
  index is sorted by form type and its 13F block sits near the start, so only a prefix is
  fetched (HTTP Range). A quarter is final once fetched two days after it ends (as in A7).
* entity_name: the current `name` in the CIK's submissions JSON, fetched only for candidates
  that reach the answer.
`has_13f_filings` with `as_of` goes through `rules.visible` (§3). Candidates whose names match
the holdings blocklist are left out while redaction is on (REGISTER A27, N1).
"""

from __future__ import annotations

import datetime as dt
import heapq
import json
import re
import threading
import time
import zlib
from collections import Counter
from pathlib import Path

from . import blocklist, rules
from .config import write_json
from .sec_client import SecUnavailable

NAMES_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
INDEX_URL = "https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.gz"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FIRST_YEAR = 1993  # EDGAR's full index starts here; it lists 13F-HR filings from 1993 QTR1
DAY = 86400.0
RANGE = 1 << 20  # first prefix fetched per quarter (the 13F block ends within 576 KiB; STAGE_4)
LAST_FORM = max(rules.ALL_FORMS)  # "13F-NT/A": a line sorting after it ends the 13F block
DEFAULT_LIMIT = 10
NOTE = {
    False: "entity_name is EDGAR's current name, and names are matched against every current and former "
    "EDGAR name, so this tool is not point-in-time for names. has_13f_filings is true if EDGAR lists a "
    "13F-HR, 13F-HR/A, 13F-NT or 13F-NT/A by the CIK (index up to a day behind).",
    True: "entity_name is EDGAR's current name, and names are matched against every current and former "
    "EDGAR name, so this tool is not point-in-time for names. has_13f_filings is true only if a 13F-HR, "
    "13F-HR/A, 13F-NT or 13F-NT/A dated on or before as_of exists.",
}


def _has(cik: str, first: str | None, as_of: str | None) -> bool:
    if first is None:
        return False
    probe = rules.Filing(cik=cik, accession_number="", form_type="13F-HR", filing_date=first,
                         period_of_report=None)
    return as_of is None or rules.visible(probe, as_of)


def _blocked(names) -> bool:
    return blocklist.redacting() and any(blocklist.is_blocked(n, None, None) for n in names)


def find(directory, a: dict) -> dict:
    """A4 answer for validated args: candidates with 13F filings first, then by current name."""
    as_of, limit = a.get("as_of"), a.get("limit", DEFAULT_LIMIT)
    found = directory.search(a["name"])
    first = directory.first_13f(as_of) if found else {}
    # Heap keys start at the smallest EDGAR name of each CIK, a lower bound of its current name.
    heap = [(not _has(c, first.get(c), as_of), min(names), int(c), c, None) for c, names in found.items()]
    heapq.heapify(heap)
    out = []
    while heap and len(out) < limit:
        miss, key, n, cik, name = heapq.heappop(heap)
        if name is None:
            name = directory.current_name(cik) or key
            if name.upper() != key:  # sorts under its current name: put it back there
                heapq.heappush(heap, (miss, name.upper(), n, cik, name))
                continue
        if not _blocked((*found[cik], name)):
            out.append(((miss, name.upper(), n), {"cik": cik, "entity_name": name, "has_13f_filings": not miss}))
    out.sort(key=lambda t: t[0])
    return {"query": a["name"], "candidates": [c for _, c in out], "note": NOTE[as_of is not None]}


def _form(line: bytes) -> str:
    return line.split(b"  ", 1)[0].strip().decode("latin-1")


def index_block(text: bytes) -> tuple[dict[str, str], bool]:
    """From a decompressed prefix of form.idx (sorted by form type): the earliest 13F filing
    date per CIK, and whether the prefix reaches past the 13F block."""
    head = text.find(b"\n---")
    body = text[text.find(b"\n", head + 1) + 1:text.rfind(b"\n")] if head >= 0 else b""
    at = body.find(b"13F-")
    start = body.rfind(b"\n", 0, at) + 1 if at >= 0 else body.rfind(b"\n") + 1
    first: dict[str, str] = {}
    for line in body[start:].split(b"\n"):
        form = _form(line)
        if form in rules.ALL_FORMS:
            tok = line.split()
            cik, date = str(int(tok[-3])), tok[-2].decode()
            first[cik] = min(date, first.get(cik, date))
        elif form > LAST_FORM:
            return first, True
    return first, False


def _ts(day: dt.date) -> float:
    return dt.datetime.combine(day, dt.time(), tzinfo=dt.timezone.utc).timestamp()


def _fresh(mtime: float, start: dt.date, end: dt.date, as_of: str | None) -> bool:
    """Can a quarter's cached index (written at `mtime`) answer for `as_of`?"""
    if mtime >= _ts(end + dt.timedelta(days=2)):
        return True  # the quarter was complete when fetched
    if as_of is None:
        return mtime >= time.time() - DAY
    if as_of < start.isoformat():
        return True  # nothing in it is dated on or before as_of
    return mtime >= _ts(dt.date.fromisoformat(as_of) + dt.timedelta(days=2))


class EdgarDirectory:
    def __init__(self, client, cache: Path) -> None:
        self.client = client
        self.dir = cache / "f13index"
        self._names: tuple[float, str, dict[str, tuple[str, ...]]] | None = None
        self._first: dict[str, str] = {}
        self._loaded: dict[str, float] = {}
        self._lock = threading.Lock()  # tool calls run in worker threads: build each index once

    def _lookup(self) -> tuple[str, dict[str, tuple[str, ...]]]:
        """The CIK lookup text (upper case) and every name of each CIK that has several."""
        with self._lock:
            return self._load_names()

    def _load_names(self) -> tuple[str, dict[str, tuple[str, ...]]]:
        if self._names is None or self._names[0] < time.time() - DAY:
            body = self.client.get(NAMES_URL, fetched_after=time.time() - DAY) or b""
            text = body.decode("latin-1").upper()
            del body
            twice = {c for c, k in Counter(re.findall(r":(\d+):$", text, re.M)).items() if k > 1}
            multi: dict[str, list[str]] = {}
            for m in re.finditer(r"^(.*):(\d+):$", text, re.M):
                if m.group(2) in twice:
                    multi.setdefault(str(int(m.group(2))), []).append(m.group(1))
            self._names = (time.time(), text, {c: tuple(v) for c, v in multi.items()})
        return self._names[1], self._names[2]

    def search(self, name: str) -> dict[str, tuple[str, ...]]:
        text, multi = self._lookup()
        q, out = name.upper(), {}
        i = text.find(q)
        while i != -1:
            s, e = text.rfind("\n", 0, i) + 1, text.find("\n", i)
            e = len(text) if e < 0 else e
            entity, _, cik = text[s:e].rstrip(":").rpartition(":")
            if q in entity and cik.isdigit():
                out.setdefault(str(int(cik)), multi.get(str(int(cik)), (entity,)))
            i = text.find(q, e)
        return out

    def first_13f(self, as_of: str | None) -> dict[str, str]:
        with self._lock:
            self._update(as_of)
            return dict(self._first)

    def _update(self, as_of: str | None) -> None:
        today = dt.datetime.now(dt.timezone.utc).date()
        for y in range(FIRST_YEAR, today.year + 1):
            for q in range(1, 5):
                start = dt.date(y, 3 * q - 2, 1)
                if start > today:
                    break
                end = dt.date(y + q // 4, 3 * q % 12 + 1, 1) - dt.timedelta(days=1)
                path = self.dir / f"{y}Q{q}.json"
                if not path.exists() or not _fresh(path.stat().st_mtime, start, end, as_of):
                    found = self._fetch(INDEX_URL.format(y=y, q=q))
                    if found is None and time.time() >= _ts(end + dt.timedelta(days=2)):
                        raise SecUnavailable(f"EDGAR has no form index for {y} QTR{q}")  # never cache as final
                    write_json(path, found or {})
                if self._loaded.get(path.name) != path.stat().st_mtime:
                    for cik, date in json.loads(path.read_text()).items():
                        self._first[cik] = min(date, self._first.get(cik, date))
                    self._loaded[path.name] = path.stat().st_mtime

    def _fetch(self, url: str) -> dict[str, str] | None:
        """Earliest 13F date per CIK in one quarter's form index; None if there is no index."""
        z, text, pos, size = zlib.decompressobj(16 + zlib.MAX_WBITS), b"", 0, RANGE
        while True:
            body = self.client.get(url, store=False, headers={"Range": f"bytes={pos}-{pos + size - 1}"})
            if body is None:
                return None if pos == 0 else index_block(text)[0]
            text += z.decompress(body)
            first, done = index_block(text)
            if done or z.eof or len(body) < size:
                return first
            pos, size = pos + len(body), size * 2

    def current_name(self, cik: str) -> str | None:
        body = self.client.get(SUBMISSIONS_URL.format(cik=int(cik)), fetched_after=time.time() - DAY)
        return (json.loads(body).get("name") or None) if body else None
