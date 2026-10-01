"""Parsers for 13F XML documents (cover page and information table).

`parse_infotable` applies the blocklist to each row before reading any other
field of it; blocked rows are discarded immediately and never leave this module.
Only `redact=False` (EDGAR13F_REDACT=off, see `blocklist.redacting`) skips it.
"""

from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

from . import blocklist


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _find(elem: ET.Element, *path: str) -> ET.Element | None:
    cur: ET.Element | None = elem
    for name in path:
        if cur is None:
            return None
        cur = next((c for c in cur if _local(c.tag) == name), None)
    return cur


def _text(elem: ET.Element, *path: str) -> str | None:
    node = _find(elem, *path)
    if node is None or node.text is None:
        return None
    txt = node.text.strip()
    return txt or None


def mdy_to_iso(text: str | None) -> str | None:
    """'MM-DD-YYYY' (13F XML date format) -> 'YYYY-MM-DD'."""
    if not text:
        return None
    parts = text.strip().split("-")
    if len(parts) == 3 and len(parts[2]) == 4:
        return f"{parts[2]}-{parts[0]:0>2}-{parts[1]:0>2}"
    if len(parts) == 3 and len(parts[0]) == 4:
        return text.strip()
    return None


def parse_cover(xml: bytes) -> dict:
    root = ET.fromstring(xml)
    cover = _find(root, "formData", "coverPage")
    if cover is None:
        cover = ET.Element("coverPage")
    amend_no = _text(cover, "amendmentNo")
    amend_type = _text(cover, "amendmentInfo", "amendmentType")
    return {
        "period_of_report": mdy_to_iso(_text(cover, "reportCalendarOrQuarter"))
        or mdy_to_iso(_text(root, "headerData", "filerInfo", "periodOfReport")),
        "amendment_no": int(amend_no) if amend_no and amend_no.isdigit() else None,
        "amendment_type": amend_type.upper() if amend_type else None,
        "report_type": _text(cover, "reportType"),
        "filing_manager_name": _text(cover, "filingManager", "name"),
    }


def _int(text: str | None) -> int | None:
    if text is None:
        return None
    try:
        return int(Decimal(text.replace(",", "").strip()))
    except (InvalidOperation, ValueError):
        return None


def _upper(text: str | None) -> str | None:
    return text.upper() if text else None


def _kids(elem: ET.Element | None) -> dict[str, ET.Element]:
    """First child per local name (what `_find` returns), collected in one pass."""
    out: dict[str, ET.Element] = {}
    for child in elem if elem is not None else ():
        out.setdefault(_local(child.tag), child)
    return out


def _txt(node: ET.Element | None) -> str | None:
    if node is None or node.text is None:
        return None
    return node.text.strip() or None


def _blocked(name: str | None, title: str | None, cusip: str | None, seen: dict) -> bool:
    key = (name, title, cusip)
    if key not in seen:  # is_blocked is a pure function of these three fields
        seen[key] = blocklist.is_blocked(name, title, cusip)
    return seen[key]


def _row(node: ET.Element, accession: str, redact: bool = True, seen: dict | None = None) -> dict | None:
    kids = _kids(node)
    name = _txt(kids.get("nameOfIssuer"))
    title = _txt(kids.get("titleOfClass"))
    cusip = _txt(kids.get("cusip"))
    if redact and _blocked(name, title, cusip, {} if seen is None else seen):
        return None  # redacted before any other field is read
    shr, vote = _kids(kids.get("shrsOrPrnAmt")), _kids(kids.get("votingAuthority"))
    return {
        "accession_number": accession,
        "name_of_issuer": name or "",
        "title_of_class": title or "",
        "cusip": cusip or "",
        "figi": _txt(kids.get("figi")),
        "value": _int(_txt(kids.get("value"))),
        "shares_or_principal_amount": _int(_txt(shr.get("sshPrnamt"))),
        "sh_prn": _upper(_txt(shr.get("sshPrnamtType"))),
        "put_call": _upper(_txt(kids.get("putCall"))),
        "investment_discretion": _txt(kids.get("investmentDiscretion")),
        "other_manager": _txt(kids.get("otherManager")),
        "voting_authority_sole": _int(_txt(vote.get("Sole"))),
        "voting_authority_shared": _int(_txt(vote.get("Shared"))),
        "voting_authority_none": _int(_txt(vote.get("None"))),
    }


_XML_BLOCK = re.compile(rb"<XML>\s*(.*?)\s*</XML>", re.DOTALL | re.IGNORECASE)


def submission_xml(text: bytes) -> list[bytes]:
    """The <XML> documents embedded in an EDGAR full submission text file (.txt)."""
    return _XML_BLOCK.findall(text)


def is_infotable(xml: bytes) -> bool:
    for _event, elem in ET.iterparse(io.BytesIO(xml), events=("start",)):
        return _local(elem.tag) == "informationTable"
    return False


def parse_infotable(xml: bytes, accession: str, redact: bool = True) -> list[dict]:
    """Rows of an information table, blocklisted rows removed unless redact=False. Order as filed."""
    rows: list[dict] = []
    seen: dict = {}
    for _event, elem in ET.iterparse(io.BytesIO(xml), events=("end",)):
        if _local(elem.tag) != "infoTable":
            continue
        row = _row(elem, accession, redact, seen)
        elem.clear()
        if row is not None:
            rows.append(row)
    return rows
