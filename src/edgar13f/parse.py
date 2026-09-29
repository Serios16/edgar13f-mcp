"""Parsers for 13F XML documents (cover page and information table).

`parse_infotable` applies the blocklist to each row before reading any other
field of it; blocked rows are discarded immediately and never leave this module.
"""

from __future__ import annotations

import io
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


def _row(node: ET.Element, accession: str) -> dict | None:
    name = _text(node, "nameOfIssuer")
    title = _text(node, "titleOfClass")
    cusip = _text(node, "cusip")
    if blocklist.is_blocked(name, title, cusip):
        return None  # redacted before any other field is read
    return {
        "accession_number": accession,
        "name_of_issuer": name or "",
        "title_of_class": title or "",
        "cusip": cusip or "",
        "figi": _text(node, "figi"),
        "value": _int(_text(node, "value")),
        "shares_or_principal_amount": _int(_text(node, "shrsOrPrnAmt", "sshPrnamt")),
        "sh_prn": _upper(_text(node, "shrsOrPrnAmt", "sshPrnamtType")),
        "put_call": _upper(_text(node, "putCall")),
        "investment_discretion": _text(node, "investmentDiscretion"),
        "other_manager": _text(node, "otherManager"),
        "voting_authority_sole": _int(_text(node, "votingAuthority", "Sole")),
        "voting_authority_shared": _int(_text(node, "votingAuthority", "Shared")),
        "voting_authority_none": _int(_text(node, "votingAuthority", "None")),
    }


def is_infotable(xml: bytes) -> bool:
    for _event, elem in ET.iterparse(io.BytesIO(xml), events=("start",)):
        return _local(elem.tag) == "informationTable"
    return False


def parse_infotable(xml: bytes, accession: str) -> list[dict]:
    """Rows of an information table, blocklisted rows removed. Order as filed."""
    rows: list[dict] = []
    for _event, elem in ET.iterparse(io.BytesIO(xml), events=("end",)):
        if _local(elem.tag) != "infoTable":
            continue
        row = _row(elem, accession)
        elem.clear()
        if row is not None:
            rows.append(row)
    return rows
