"""Blocklist invariants (hard rule 2), proven on synthetic rows only.

No real blocklisted row is ever loaded here: the synthetic rows below are
invented, carry zero values, and exist only to prove redaction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from edgar13f import blocklist, parse, server, tools
from edgar13f.rules import Filing
from edgar13f.sources import EdgarSource
from tests.conftest import REPO

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
    return sorted(FIXTURES.glob("**/rows/*.json"))  # recorded and synthetic


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


def test_infotable_shadowed_by_edgar_index_xml_is_read_from_submission_text(tmp_path):
    """A filer's table named index.xml is served by EDGAR as a directory listing; the rows
    come from the full submission .txt instead, still redacted, and the .txt is never cached."""
    index = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "index.xml"}]}}
    listing = b'<?xml version="1.0"?><directory><name>/Archives/edgar/data</name></directory>'
    txt = (b"<SEC-DOCUMENT>\n<DOCUMENT>\n<TYPE>13F-HR\n<FILENAME>primary_doc.xml\n<TEXT>\n<XML>\n"
           b'<?xml version="1.0"?><edgarSubmission/>\n</XML>\n</TEXT>\n</DOCUMENT>\n<DOCUMENT>\n'
           b"<TYPE>INFORMATION TABLE\n<FILENAME>index.xml\n<TEXT>\n<XML>\n" + infotable_xml(BLOCKED + KEPT)
           + b"\n</XML>\n</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>\n")
    acc = "0000000001-25-000002"
    client = _FakeClient({"index.json": json.dumps(index).encode(), "index.xml": listing, f"{acc}.txt": txt})
    f = Filing(cik="1", accession_number=acc, form_type="13F-HR", filing_date="2025-02-14",
               period_of_report="2024-12-31", primary_doc="xslForm13F_X02/primary_doc.xml")
    rows = EdgarSource(client, tmp_path).rows(f)
    assert survivors(rows) == [] and sorted(r["cusip"] for r in rows) == sorted(c for _, _, c in KEPT)
    assert not any(u.endswith((".txt", "index.xml")) for u in client.stored)


def test_submission_text_not_fetched_when_infotable_found(tmp_path):
    index = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "infotable.xml"}]}}
    client = _FakeClient({"index.json": json.dumps(index).encode(), "infotable.xml": infotable_xml(KEPT)})
    fetched = []
    get = client.get
    client.get = lambda url, **kw: fetched.append(url) or get(url, **kw)
    f = Filing(cik="1", accession_number="0000000001-25-000003", form_type="13F-HR",
               filing_date="2025-02-14", period_of_report="2024-12-31", primary_doc="primary_doc.xml")
    assert len(EdgarSource(client, tmp_path).rows(f)) == len(KEPT)
    assert not any(u.endswith(".txt") for u in fetched)


# ---------------------------------------------------------------- stage 3 (a): the EDGAR13F_REDACT switch
# Redaction is ON unless the variable is exactly "off". Tests of "off" use the invented rows
# above (zero values, made-up CUSIPs) served by a fake client: never live SEC data, never
# recorded fixtures. Only counts are asserted; no row is printed.

ACC = "0000000001-25-000009"
FILING = Filing(cik="1", accession_number=ACC, form_type="13F-HR", filing_date="2025-02-14",
                period_of_report="2024-12-31", primary_doc="primary_doc.xml")
NOT_OFF = [None, "", "on", "ON", "OFF", "Off", " off", "off ", "0", "false", "no", "disabled", "of"]


class _Synthetic:
    """Serves one synthetic filing; records every URL asked for."""

    def __init__(self):
        index = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "infotable.xml"}]}}
        self.files = {"index.json": json.dumps(index).encode(), "infotable.xml": infotable_xml(BLOCKED + KEPT)}
        self.asked: list[str] = []

    def get(self, url, store=True, fetched_after=None):
        self.asked.append(url)
        return self.files.get(url.rsplit("/", 1)[-1])


def _set(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("EDGAR13F_REDACT", raising=False)
    else:
        monkeypatch.setenv("EDGAR13F_REDACT", value)


@pytest.mark.parametrize("value", NOT_OFF, ids=repr)
def test_redaction_on_unless_exactly_off(monkeypatch, tmp_path, value):
    _set(monkeypatch, value)
    assert blocklist.redacting() is True
    rows = EdgarSource(_Synthetic(), tmp_path).rows(FILING)
    assert survivors(rows) == [] and len(rows) == len(KEPT)
    assert (tmp_path / "rows" / f"{ACC}.json").exists() and not (tmp_path / "rows-unredacted").exists()


def test_off_keeps_every_synthetic_row_in_a_separate_cache(monkeypatch, tmp_path):
    _set(monkeypatch, "off")
    assert blocklist.redacting() is False
    rows = EdgarSource(_Synthetic(), tmp_path).rows(FILING)
    assert len(survivors(rows)) == len(BLOCKED) and len(rows) == len(BLOCKED) + len(KEPT)
    assert (tmp_path / "rows-unredacted" / f"{ACC}.json").exists() and not (tmp_path / "rows").exists()


def test_cache_written_with_off_is_never_read_with_redaction_on(monkeypatch, tmp_path):
    _set(monkeypatch, "off")
    EdgarSource(_Synthetic(), tmp_path).rows(FILING)
    _set(monkeypatch, None)
    client = _Synthetic()
    rows = EdgarSource(client, tmp_path).rows(FILING)
    assert survivors(rows) == [] and len(rows) == len(KEPT)
    assert any(u.endswith("infotable.xml") for u in client.asked)  # re-read and redacted, not taken from cache


def test_parse_default_redacts_whatever_the_switch(monkeypatch):
    _set(monkeypatch, "off")
    xml = infotable_xml(BLOCKED + KEPT)
    assert survivors(parse.parse_infotable(xml, ACC)) == []
    assert len(survivors(parse.parse_infotable(xml, ACC, redact=False))) == len(BLOCKED)


def test_planted_failure_switch_ignored_is_detected(monkeypatch, tmp_path):
    _set(monkeypatch, "off")
    monkeypatch.setattr(blocklist, "redacting", lambda: True)  # a switch that does nothing
    rows = EdgarSource(_Synthetic(), tmp_path).rows(FILING)
    assert len(survivors(rows)) != len(BLOCKED)  # the "off" test above would fail


def test_server_refuses_off_with_a_fixture_dir(monkeypatch, tmp_path):
    _set(monkeypatch, "off")
    monkeypatch.setenv("EDGAR13F_FIXTURE_DIR", str(tmp_path))  # empty dir: no recorded fixture is read
    with pytest.raises(SystemExit):
        server.make_source()


SETS_SWITCH = re.compile(r"""EDGAR13F_REDACT\s*[=:]|setenv\(\s*["']EDGAR13F_REDACT|["']EDGAR13F_REDACT["']\s*[]:,]""")


def test_no_ci_job_test_or_tool_sets_the_switch():
    allowed = {"tests/conftest.py", "tests/invariants/test_blocklist.py"}
    hits = []
    for pattern in (".github/workflows/*", "tests/**/*.py", "tests/**/*.sh"):
        for path in REPO.glob(pattern):
            rel = str(path.relative_to(REPO))
            if path.is_file() and rel not in allowed and SETS_SWITCH.search(path.read_text()):
                hits.append(rel)
    assert hits == []


@pytest.mark.parametrize("line", ['  EDGAR13F_REDACT: "off"', "EDGAR13F_REDACT=off python -m edgar13f.server",
                                  'monkeypatch.setenv("EDGAR13F_REDACT", "off")', 'env={"EDGAR13F_REDACT": "off"}',
                                  'os.environ["EDGAR13F_REDACT"] = "off"'])
def test_planted_switch_settings_are_detected(line):
    assert SETS_SWITCH.search(line)


# Stage 4 (Addendum A): redaction comes before every new filter, and find_manager leaves out
# candidates whose EDGAR names match the blocklist. Synthetic rows and invented entities only.

class _SyntheticManager:
    """get_holdings_as_of over the synthetic filing above, rows read through EdgarSource."""

    def __init__(self, tmp_path):
        self.edgar = EdgarSource(_Synthetic(), tmp_path)

    def filings(self, cik, as_of, periods=None):
        return [FILING]

    def rows(self, f):
        return self.edgar.rows(f)


HOLD = {"cik": "1", "period": "2024-12-31", "as_of": "2025-08-27"}


@pytest.mark.parametrize("extra", [{"issuer": "gold"}, {"issuer": "S&P 500"}, {"issuer": "ENERGY"}, {"issuer": "tr"},
                                   {"max_positions": 200}, {"issuer": "spdr", "max_positions": 1}])
def test_new_filters_never_see_redacted_rows(tmp_path, extra):
    out = tools.call(_SyntheticManager(tmp_path), "get_holdings_as_of", {**HOLD, **extra})
    assert out["status"] == "ok" and survivors(out["holdings"]) == []
    assert survivors([{"cusip": c} for c in out.get("matched_cusips", [])]) == []
    if "max_positions" in extra and "issuer" not in extra:
        assert out["total_positions"] == len(KEPT)


def test_agent_mode_never_sees_redacted_rows(tmp_path, monkeypatch):
    monkeypatch.setenv("EDGAR13F_AGENT_MODE", "on")
    out = tools.call(_SyntheticManager(tmp_path), "get_holdings_as_of", HOLD)
    assert out["auto_limited"] is True and survivors(out["holdings"]) == [] and out["total_positions"] == len(KEPT)


def test_issuer_filter_would_see_them_with_the_switch_off(monkeypatch, tmp_path):
    _set(monkeypatch, "off")  # synthetic rows only: shows the test above can fail
    out = tools.call(_SyntheticManager(tmp_path), "get_holdings_as_of", {**HOLD, "issuer": "gold"})
    assert len(survivors(out["holdings"])) > 0


class _Entities:
    """find_manager directory of invented entities named like the synthetic blocked rows."""

    def __init__(self):
        names = [n for n, _, _ in BLOCKED[:26]] + [n for n, _, _ in KEPT]
        self.entities = {str(i + 1): n.upper() for i, n in enumerate(names)}

    def search(self, name):
        return {c: (n,) for c, n in self.entities.items() if name.upper() in n}

    def first_13f(self, as_of):
        return {c: "2001-01-02" for c in self.entities}

    def current_name(self, cik):
        return self.entities[cik]


class _EntitySource:
    directory = _Entities()


def _found(name):
    out = tools.call(_EntitySource(), "find_manager", {"name": name, "limit": 20})
    return [c["entity_name"] for c in out["candidates"]]


# Ruling N1 (2026-10-02): find_manager returns entity names unfiltered; rule 2 covers holdings
# rows, their values and prices. Names that by themselves match the list are still returned.
NAMED = {"SPDR GOLD TR", "SPDR GOLD TRUST", "ISHARES GOLD TR", "SPDR GOLD MINISHARES TRUST", "ABRDN GOLD ETF TRUST",
         "SPROTT PHYSICAL GOLD TR", "GOLDMAN SACHS PHYSICAL GOLD ETF", "ISHARES PHYSICAL GOLD ETC",
         "SPDR S&P 500 ETF TR", "VANGUARD 500 INDEX FUND", "ISHARES CORE S&P 500 UCITS ETF",
         "INVESCO S&P 500 UCITS ETF", "SPDR GOLD UCITS COPY"}


def test_find_manager_returns_entities_named_like_blocked_instruments():
    assert all(blocklist.is_blocked(n, None, None) for n in NAMED)  # each name matches the list
    found = set(_found("GOLD")) | set(_found("S&P 500")) | set(_found("500 INDEX"))
    assert NAMED <= found
    assert {"BARRICK GOLD CORP", "GOLDMAN SACHS GROUP INC"} <= set(_found("GOLD"))


def test_find_manager_answers_the_same_whatever_the_blocklist(monkeypatch):
    before = _found("GOLD")
    monkeypatch.setattr(blocklist, "is_blocked", lambda *a: True)
    assert _found("GOLD") == before
