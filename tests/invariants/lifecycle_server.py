"""Offline server for the lifecycle tests: `python -m tests.invariants.lifecycle_server`.

The real `edgar13f.server` stdio loop over the real `EdgarSource` and `SecClient` (cache dir,
rate limiter, atomic writes), with an opener that answers from the synthetic fixture manager
(benign rows only) instead of sec.gov; sockets are refused, so nothing leaves the machine.

Environment:
  EDGAR13F_CACHE_DIR      cache dir (required)
  LIFECYCLE_MARKER        file created when a slow request is in flight
  LIFECYCLE_SLOW_AFTER    information tables answered at full speed before the slow ones (default: all fast)
  LIFECYCLE_INFLATE       repeat each table's rows this many times (large cache writes; default 1)
  LIFECYCLE_PLANT         planted defects for the controls: "partial-write" (rows written straight to their
                          final name, half first), "ignore-sigterm", "ignore-stdin-eof", "exit-on-garbage"
                          (the process exits on a stdin line that is not JSON)
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path
from xml.sax.saxutils import escape

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"
DATA = "https://data.sec.gov/submissions"
ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
USER_AGENT = "edgar13f lifecycle test (offline; no request leaves the machine)"


def _el(tag: str, value) -> str:
    return f"<{tag}>{escape(str(value))}</{tag}>" if value not in (None, "") else ""


def _mdy(iso: str | None) -> str | None:
    return f"{iso[5:7]}-{iso[8:10]}-{iso[:4]}" if iso else None


def _cover(f: dict) -> bytes:
    amend = f"<amendmentInfo>{_el('amendmentType', f['amendment_type'])}</amendmentInfo>" if f["amendment_type"] else ""
    return (f'<?xml version="1.0"?><edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler"><formData>'
            f"<coverPage>{_el('reportCalendarOrQuarter', _mdy(f['period_of_report']))}"
            f"{_el('amendmentNo', f['amendment_no'])}{amend}<filingManager>{_el('name', f['filing_manager_name'])}"
            f"</filingManager>{_el('reportType', f['report_type'])}</coverPage></formData></edgarSubmission>").encode()


def _table(rows: list[dict]) -> bytes:
    def one(r: dict) -> str:
        shr = _el("sshPrnamt", r["shares_or_principal_amount"]) + _el("sshPrnamtType", r["sh_prn"])
        vote = (_el("Sole", r["voting_authority_sole"]) + _el("Shared", r["voting_authority_shared"])
                + _el("None", r["voting_authority_none"]))
        return (f"<infoTable>{_el('nameOfIssuer', r['name_of_issuer'])}{_el('titleOfClass', r['title_of_class'])}"
                f"{_el('cusip', r['cusip'])}{_el('figi', r['figi'])}{_el('value', r['value'])}"
                f"<shrsOrPrnAmt>{shr}</shrsOrPrnAmt>{_el('putCall', r['put_call'])}"
                f"{_el('investmentDiscretion', r['investment_discretion'])}{_el('otherManager', r['other_manager'])}"
                f"<votingAuthority>{vote}</votingAuthority></infoTable>")
    return ('<?xml version="1.0"?><informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">'
            + "".join(one(r) for r in rows) + "</informationTable>").encode()


def fake_edgar(root: Path = FIXTURES, inflate: int = 1) -> dict[str, bytes]:
    """URL -> body for every synthetic manager under `root` (each table's rows repeated `inflate` times)."""
    files: dict[str, bytes] = {}
    for path in sorted(root.glob("*/filings.json")):
        cik = path.parent.name
        filings = sorted(json.loads(path.read_text())["filings"], key=lambda f: f["filing_date"], reverse=True)
        recent = {"accessionNumber": [f["accession_number"] for f in filings],
                  "filingDate": [f["filing_date"] for f in filings],
                  "reportDate": [f["period_of_report"] or "" for f in filings],
                  "form": [f["form_type"] for f in filings],
                  "primaryDocument": [f["primary_doc"] or "" for f in filings]}
        files[f"{DATA}/CIK{int(cik):010d}.json"] = json.dumps(
            {"cik": cik, "filings": {"recent": recent, "files": []}}).encode()
        for f in filings:
            folder = f"{ARCHIVES}/{cik}/{f['accession_number'].replace('-', '')}"
            table = path.parent / "rows" / f"{f['accession_number']}.json"
            items = [{"name": "primary_doc.xml"}] + ([{"name": "infotable.xml"}] if table.exists() else [])
            files[f"{folder}/primary_doc.xml"] = _cover(f)
            files[f"{folder}/index.json"] = json.dumps({"directory": {"item": items}}).encode()
            if table.exists():  # notices carry no information table
                files[f"{folder}/infotable.xml"] = _table(json.loads(table.read_text()) * inflate)
    return files


def cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _refuse(*_a, **_k):
    raise OSError("network access is disabled in the lifecycle server")


def _opener(files: dict[str, bytes], marker: Path | None, slow_after: int | None):
    tables = [0]

    def opener(req, _timeout):
        url = req.full_url
        if url.endswith("/infotable.xml"):
            tables[0] += 1
            if slow_after is not None and tables[0] > slow_after:
                if marker:
                    marker.write_text(f"{os.getpid()} {url}")
                time.sleep(3600)  # in flight until the test signals the process
        return (200, files[url], {}) if url in files else (404, b"", {})

    return opener


def _partial_write(path: Path, obj: object) -> None:
    """Planted defect: non-atomic write, killed halfway (the marker is created once half is on disk)."""
    text = json.dumps(obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text[: len(text) // 2])
        fh.flush()
        marker = os.environ.get("LIFECYCLE_MARKER")
        if marker:
            Path(marker).write_text(f"{os.getpid()} {path}")
        time.sleep(3600)
        fh.write(text[len(text) // 2:])


def _exit_on_garbage() -> None:
    """Planted defect: stdin goes through a filter that ends the process on a non-JSON line."""
    read_fd, write_fd = os.pipe()

    def pump() -> None:
        for line in sys.stdin.buffer:
            try:
                json.loads(line)
            except ValueError:
                os._exit(3)
            os.write(write_fd, line)
        os.close(write_fd)

    threading.Thread(target=pump, daemon=True).start()
    sys.stdin = io.TextIOWrapper(os.fdopen(read_fd, "rb"), encoding="utf-8")


def main() -> None:
    socket.socket.connect = _refuse
    socket.create_connection = _refuse
    import anyio
    from mcp.server.stdio import stdio_server

    from edgar13f import server, sources
    from edgar13f.sec_client import SecClient

    plant = os.environ.get("LIFECYCLE_PLANT", "")
    cache = Path(os.environ["EDGAR13F_CACHE_DIR"])
    marker = Path(os.environ["LIFECYCLE_MARKER"]) if os.environ.get("LIFECYCLE_MARKER") else None
    slow = os.environ.get("LIFECYCLE_SLOW_AFTER")
    if plant == "partial-write":
        sources._write_json = _partial_write
    if plant == "exit-on-garbage":
        _exit_on_garbage()
    if plant == "ignore-sigterm":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    files = fake_edgar(inflate=int(os.environ.get("LIFECYCLE_INFLATE", "1")))
    client = SecClient(cache, USER_AGENT, opener=_opener(files, marker, int(slow) if slow else None))
    source = sources.EdgarSource(client, cache)

    async def serve() -> None:  # as server._serve, on the offline source
        srv = server.build_server(source)
        async with stdio_server() as (read_stream, write_stream):
            await srv.run(read_stream, write_stream, srv.create_initialization_options())
        if plant == "ignore-stdin-eof":
            await anyio.sleep(3600)

    anyio.run(serve)


if __name__ == "__main__":
    main()
