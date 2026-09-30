"""Blocklist invariants (hard rule 2), proven on synthetic rows only.

No real blocklisted row is ever loaded here: the synthetic rows below are
invented, carry zero values, and exist only to prove redaction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar13f import blocklist, parse
from edgar13f.rules import Filing
from edgar13f.sources import EdgarSource

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

# (nameOfIssuer, titleOfClass, cusip) - synthetic; spans the four categories and spellings.
BLOCKED = [
    ("SPDR GOLD TR", "GOLD SHS", "000000001"),
    ("spdr gold trust", "gold shs", "000000002"),
    ("Ishares Gold Tr", "Ishares New", "000000003"),
    ("SPDR GOLD MINISHARES TRUST", "SHS", "000000004"),
    ("abrdn Gold ETF Trust", "PHYSCL GOLD SHS", "000000005"),
    ("SPROTT PHYSICAL GOLD TR", "UNIT", "000000006"),
    ("GOLDMAN SACHS PHYSICAL GOLD ETF", "SHS", "000000007"),
    ("iShares Physical Gold ETC", "USD", "000000008"),
    ("SELECT SECTOR SPDR TR", "ENERGY", "000000009"),
    ("Select Sector Spdr Tr", "sbi int-energy", "000000010"),
    ("VANGUARD WORLD FDS", "ENERGY ETF", "000000011"),
    ("ISHARES TR", "U.S. ENERGY ETF", "000000012"),
    ("SPDR SER TR", "S&P OILGAS EXP", "000000013"),
    ("FIDELITY COVINGTON TRUST", "MSCI ENERGY IDX", "000000014"),
    ("VANECK ETF TRUST", "OIL SVCS ETF", "000000015"),
    ("VANGUARD INDEX FDS", "S&P 500 ETF SHS", "000000016"),
    ("ISHARES TR", "CORE S&P500 ETF", "000000017"),
    ("SPDR S&P 500 ETF TR", "TR UNIT", "000000018"),
    ("INVESCO EXCHANGE TRADED FD T", "S&P500 EQL WGT", "000000019"),
    ("DIREXION SHS ETF TR", "DAILY S&P500 BULL 3X", "000000020"),
    ("PROSHARES TR", "ULTRA S&P500", "000000021"),
    ("SPDR SERIES TRUST", "PORTFOLIO S&P 500", "000000022"),
    ("VANGUARD 500 INDEX FUND", "ADMIRAL", "000000023"),
    ("ISHARES CORE S&P 500 UCITS ETF", "USD ACC", "000000024"),
    ("INVESCO S&P 500 UCITS ETF", "ACC", "000000025"),
    ("SPDR GOLD UCITS COPY", "ACC", "000000026"),
    # CUSIP-only matches (neutral names), incl. lowercase CUSIP.
    ("SYNTHETIC HOLDING A", "COM", "78462F103"),
    ("SYNTHETIC HOLDING B", "COM", "922908363"),
    ("SYNTHETIC HOLDING C", "COM", "81369y506"),
    ("SYNTHETIC HOLDING D", "COM", "78463v107"),
    ("SYNTHETIC HOLDING E", "COM", "464285204"),
]

KEPT = [
    ("APPLE INC", "COM", "037833100"),
    ("BARRICK GOLD CORP", "COM", "067901108"),
    ("GOLDMAN SACHS GROUP INC", "COM", "38141G104"),
    ("CHEVRON CORP NEW", "COM", "166764100"),
    ("EXXON MOBIL CORP", "COM", "30231G102"),
    ("ENERGY TRANSFER L P", "COM UT LTD PTN", "29273V100"),
    ("NEXTERA ENERGY INC", "COM", "65339F101"),
]


def infotable_xml(rows) -> bytes:
    items = "".join(
        f"<infoTable><nameOfIssuer>{n.replace('&', '&amp;')}</nameOfIssuer>"
        f"<titleOfClass>{t.replace('&', '&amp;')}</titleOfClass><cusip>{c}</cusip><value>0</value>"
        "<shrsOrPrnAmt><sshPrnamt>0</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>"
        "<investmentDiscretion>SOLE</investmentDiscretion><votingAuthority><Sole>0</Sole>"
        "<Shared>0</Shared><None>0</None></votingAuthority></infoTable>"
        for n, t, c in rows
    )
    return ('<?xml version="1.0"?><informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/'
            f'informationtable">{items}</informationTable>').encode()


def survivors(parsed: list[dict]) -> list[str]:
    """Synthetic blocked CUSIPs that survived parsing (independent of blocklist.py)."""
    blocked = {c.upper() for _, _, c in BLOCKED}
    return [r["cusip"] for r in parsed if r["cusip"].upper() in blocked]


def test_parse_drops_every_synthetic_blocked_row_and_keeps_benign():
    parsed = parse.parse_infotable(infotable_xml(BLOCKED + KEPT), "0000000000-00-000000")
    assert survivors(parsed) == []
    assert sorted(r["cusip"] for r in parsed) == sorted(c for _, _, c in KEPT)


@pytest.mark.parametrize("row", BLOCKED, ids=[c for _, _, c in BLOCKED])
def test_each_blocked_row_matches(row):
    assert blocklist.is_blocked(*row)


def test_planted_failure_disabled_blocklist_is_detected(monkeypatch):
    monkeypatch.setattr(blocklist, "is_blocked", lambda *a: False)
    parsed = parse.parse_infotable(infotable_xml(BLOCKED), "0000000000-00-000000")
    assert len(survivors(parsed)) == len(BLOCKED)  # the check can fail


class _FakeClient:
    def __init__(self, files):
        self.files, self.stored = files, []

    def get(self, url, store=True, fetched_after=None):
        if store:
            self.stored.append(url)
        return self.files.get(url.rsplit("/", 1)[-1])


def test_edgar_source_caches_only_redacted_rows(tmp_path):
    index = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "infotable.xml"}]}}
    client = _FakeClient({"index.json": json.dumps(index).encode(),
                          "infotable.xml": infotable_xml(BLOCKED + KEPT)})
    src = EdgarSource(client, tmp_path)
    f = Filing(cik="1", accession_number="0000000001-25-000001", form_type="13F-HR",
               filing_date="2025-02-14", period_of_report="2024-12-31", primary_doc="primary_doc.xml")
    rows = src.rows(f)
    assert survivors(rows) == [] and len(rows) == len(KEPT)
    assert not any(u.endswith("infotable.xml") for u in client.stored)  # raw table never cached
    cached = json.loads((tmp_path / "rows" / "0000000001-25-000001.json").read_text())
    assert survivors(cached) == [] and len(cached) == len(KEPT)


def _fixture_row_files():
    return sorted(FIXTURES.glob("*/rows/*.json"))


def test_fixtures_contain_no_blocklisted_rows():
    files = _fixture_row_files()
    assert files, "no fixtures found"
    hits = 0
    for path in files:
        for r in json.loads(path.read_text()):
            hits += blocklist.is_blocked(r["name_of_issuer"], r["title_of_class"], r["cusip"])
    assert hits == 0, f"{hits} blocklisted fixture rows"  # count only; never print rows


def test_fixtures_contain_no_blocked_cusip_anywhere():
    for path in FIXTURES.rglob("*.json"):
        text = path.read_text().upper()
        assert not any(c in text for c in blocklist.BLOCKED_CUSIPS), path.name
