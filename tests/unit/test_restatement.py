"""CONTRACTS §4 hardening: amendments and restatements, tested against the rule text.

1. `rules.resolve` against an independent oracle written from §4, over every sequence of
   up to four 13F-HR/13F-HR/A filings (kinds x same/different day x amendment_no pattern x
   accession order x as_of, with and without a notice for the period).
2. The synthetic §4 manager (`tests/fixtures/synthetic/`) end to end through the tools:
   zero-row restatement, same-day multiple amendments, UNSPECIFIED, restatement after
   NEW HOLDINGS, restatement with lowercase CUSIPs, notice restatement.
3. Restatements whose rows the blocklist removes (ruling D2), from synthetic XML parsed in
   memory; no blocked row is stored anywhere.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from edgar13f import DISCLAIMER, parse, rules, tools
from edgar13f.rules import Filing
from edgar13f.sources import FixtureSource
from tests.invariants.test_blocklist import BLOCKED, KEPT, infotable_xml, survivors

P, OTHER = "2024-12-31", "2024-09-30"
DAYS = ("2025-02-14", "2025-02-18")


# ---------------------------------------------------------------- 1. exhaustive oracle

def oracle(filings: list[Filing], period: str, as_of: str):
    """§4 verbatim: V, order, base, supplements; UNSPECIFIED treated as RESTATEMENT."""
    seen = [f for f in filings if f.filing_date <= as_of]
    v = [f for f in seen if f.form_type in ("13F-HR", "13F-HR/A") and f.period_of_report == period]
    if not v:
        nt = any(f.form_type in ("13F-NT", "13F-NT/A") and f.period_of_report == period for f in seen)
        return "notice_only" if nt else "not_yet_filed"
    v.sort(key=lambda f: (f.filing_date, float("-inf") if f.amendment_no is None else f.amendment_no,
                          f.accession_number))
    is_base = [f.form_type == "13F-HR" or f.amendment_type != "NEW HOLDINGS" for f in v]
    if not any(is_base):
        return "not_yet_filed"  # REGISTER A3
    b = max(i for i, x in enumerate(is_base) if x)
    return v[b].accession_number, [f.accession_number for f in v[b + 1:] if f.amendment_type == "NEW HOLDINGS"]


KINDS = ("O", "R", "N", "U")
AMEND = {"R": "RESTATEMENT", "N": "NEW HOLDINGS", "U": None}


def _sequences():
    for n in range(1, 5):
        for kinds in itertools.product(KINDS, repeat=n):
            if kinds.count("O") > 1:
                continue  # §4: behaviour unspecified, never evaluated
            for days in itertools.product(range(len(DAYS)), repeat=n):
                for numbering in ("in_order", "reversed", "none"):
                    for acc_order in ("in_order", "reversed"):
                        yield kinds, days, numbering, acc_order


def _build(kinds, days, numbering, acc_order, notice):
    amend_idx = [i for i, k in enumerate(kinds) if k != "O"]
    nos = {i: j + 1 for j, i in enumerate(amend_idx)}
    if numbering == "reversed":
        nos = {i: len(amend_idx) - j for j, i in enumerate(amend_idx)}
    out = []
    for i, (k, d) in enumerate(zip(kinds, days)):
        seq = i + 1 if acc_order == "in_order" else len(kinds) - i
        out.append(Filing(
            cik="1", accession_number=f"0000000001-25-{seq:06d}", form_type="13F-HR" if k == "O" else "13F-HR/A",
            filing_date=DAYS[d], period_of_report=P, amendment_type=AMEND.get(k),
            amendment_no=None if k == "O" or numbering == "none" else nos[i]))
    out.append(Filing(cik="1", accession_number="0000000001-25-000090", form_type="13F-HR",
                      filing_date=DAYS[0], period_of_report=OTHER))
    if notice:
        out.append(Filing(cik="1", accession_number="0000000001-25-000091", form_type="13F-NT",
                          filing_date=DAYS[0], period_of_report=P))
    return out


def test_resolve_matches_section4_oracle_exhaustively():
    as_ofs = ("2025-02-13", *DAYS, "2025-08-27")
    n = 0
    for kinds, days, numbering, acc_order in _sequences():
        for notice in (False, True):
            filings = _build(kinds, days, numbering, acc_order, notice)
            for as_of in as_ofs:
                got = rules.resolve(filings, P, as_of)
                want = oracle(filings, P, as_of)
                if isinstance(got, tuple):
                    got = (got[0].accession_number, [s.accession_number for s in got[1]])
                assert got == want, (kinds, days, numbering, acc_order, notice, as_of)
                n += 1
    assert n > 100_000


def test_oracle_control_detects_accession_only_ordering():
    """Planted failure: ordering by accession alone must disagree with §4 somewhere."""
    fs = _build(("O", "N", "R"), (0, 1, 1), "in_order", "reversed", False)
    base, sup = rules.resolve(fs, P, DAYS[1])
    by_acc = sorted((f for f in fs if f.period_of_report == P), key=lambda f: (f.filing_date, f.accession_number))
    assert [f.accession_number for f in by_acc][-1] != base.accession_number
    assert (base.accession_number, [s.accession_number for s in sup]) == oracle(fs, P, DAYS[1])


# ---------------------------------------------------------------- 2. synthetic manager

SYN = "9900000001"
SRC = FixtureSource(Path(__file__).resolve().parents[1] / "fixtures" / "synthetic")


def acc(suffix: str) -> str:
    return f"{SYN}-{suffix}"


def hold(period: str, as_of: str, **kw) -> dict:
    out = tools.call(SRC, "get_holdings_as_of", {"cik": SYN, "period": period, "as_of": as_of, **kw})
    assert out["disclaimer"] == DISCLAIMER
    if out["status"] == "ok":
        assert {h["accession_number"] for h in out["holdings"]} <= set(out["source_accessions"])
        assert all(a in {f.accession_number for f in SRC.filings(SYN, as_of) if f.filing_date <= as_of}
                   for a in out["source_accessions"])
    return out


def cited(out: dict):
    return out.get("reason") or out["source_accessions"]


@pytest.mark.parametrize("period,as_of,expected", [
    # zero-row restatement
    ("2024-03-31", "2024-05-19", ["24-000001"]),
    ("2024-03-31", "2024-05-20", ["24-000002"]),
    ("2024-03-31", "2025-08-27", ["24-000002"]),
    # same day: NH (no 1, acc 5), RESTATEMENT (no 2, acc 4), NH (no 3, acc 6)
    ("2024-06-30", "2024-08-19", ["24-000003"]),
    ("2024-06-30", "2024-08-20", ["24-000004", "24-000006"]),
    # UNSPECIFIED treated as RESTATEMENT
    ("2024-09-30", "2024-11-11", ["24-000007"]),
    ("2024-09-30", "2024-11-12", ["24-000008"]),
    ("2024-09-30", "2024-11-20", ["24-000008", "24-000009"]),
    # restatement after NEW HOLDINGS
    ("2024-12-31", "2025-02-19", ["25-000001"]),
    ("2024-12-31", "2025-02-20", ["25-000001", "25-000002"]),
    ("2024-12-31", "2025-03-04", ["25-000001", "25-000002"]),
    ("2024-12-31", "2025-03-05", ["25-000003"]),
    ("2024-12-31", "2025-03-15", ["25-000003", "25-000004"]),
    # lowercase restatement
    ("2025-03-31", "2025-05-19", ["25-000005"]),
    ("2025-03-31", "2025-05-20", ["25-000006"]),
    # notice restatement only
    ("2025-06-30", "2025-08-09", "not_yet_filed"),
    ("2025-06-30", "2025-08-12", "notice_only"),
    ("2025-06-30", "2025-08-27", "notice_only"),
])
def test_synthetic_section4_citations(period, as_of, expected):
    out = hold(period, as_of)
    want = expected if isinstance(expected, str) else [acc(s) for s in expected]
    assert cited(out) == want
    if out["status"] == "ok":
        assert out["accession_number"] == want[0]
        base = next(f for f in SRC.filings(SYN, as_of) if f.accession_number == want[0])
        assert out["filing_date"] == base.filing_date
        rows = [r for a in want for r in SRC.rows(next(f for f in SRC.filings(SYN, as_of) if f.accession_number == a))]
        assert out["holdings"] == rows  # as filed: no merge, no rescale, no dedupe


def test_zero_row_restatement_is_ok_with_no_holdings_and_filter_keeps_citation():
    out = hold("2024-03-31", "2024-05-20")
    assert out["status"] == "ok" and out["holdings"] == [] and out["source_accessions"] == [acc("24-000002")]
    filt = hold("2024-03-31", "2024-05-20", cusip=["90000A101"])
    assert filt == out
    diff = tools.call(SRC, "diff_holdings", {"cik": SYN, "period_a": "2024-03-31", "period_b": "2024-06-30",
                                             "as_of": "2024-08-20"})
    assert diff["accession_a"] == acc("24-000002") and diff["source_accessions_a"] == [acc("24-000002")]
    assert {c["change_type"] for c in diff["changes"]} == {"added"}
    assert all(c["shares_a"] == 0 and c["value_a"] == 0 for c in diff["changes"])


def test_same_day_restatement_drops_earlier_same_day_new_holdings():
    out = hold("2024-06-30", "2024-08-20")
    assert "90000D104" not in {h["cusip"] for h in out["holdings"]}  # NH (no 1) precedes the restatement
    assert "90000E105" in {h["cusip"] for h in out["holdings"]}      # NH (no 3) follows it


def test_restatement_with_lowercase_cusips():
    out = hold("2025-03-31", "2025-05-20")
    assert [h["cusip"] for h in out["holdings"]] == ["90000a101", "90000A101", "90000a101", "90000b102", "90000d104"]
    for asked in ("90000A101", "90000a101"):
        filt = hold("2025-03-31", "2025-05-20", cusip=[asked])
        assert len(filt["holdings"]) == 3
        assert {k: v for k, v in filt.items() if k != "holdings"} == {k: v for k, v in out.items() if k != "holdings"}
    diff = tools.call(SRC, "diff_holdings", {"cik": SYN, "period_a": "2024-12-31", "period_b": "2025-03-31",
                                             "as_of": "2025-05-20"})
    by_key = {(c["cusip"].upper(), c["put_call"]): c for c in diff["changes"]}
    assert len(by_key) == len(diff["changes"]) == 5
    long_a = by_key[("90000A101", None)]
    assert (long_a["shares_a"], long_a["shares_b"], long_a["change_type"]) == (131, 150, "increased")
    assert long_a["cusip"] == "90000a101"  # as filed, period B preferred
    assert by_key[("90000A101", "PUT")]["change_type"] == "added"
    assert by_key[("90000B102", None)]["change_type"] == "unchanged"  # case-only difference
    assert by_key[("900000103", None)]["change_type"] == "removed"
    assert by_key[("90000D104", None)]["change_type"] == "increased"


def test_list_orders_same_day_filings_by_accession():
    out = tools.call(SRC, "list_13f_filings", {"cik": SYN, "as_of": "2024-08-20"})
    same_day = [f["accession_number"] for f in out["filings"] if f["filing_date"] == "2024-08-20"]
    assert same_day == [acc("24-000004"), acc("24-000005"), acc("24-000006")]
    unspecified = tools.call(SRC, "list_13f_filings", {"cik": SYN, "as_of": "2024-11-12"})["filings"][-1]
    assert unspecified["amendment_type"] is None and unspecified["is_amendment"] is True


# ---------------------------------------------------------------- 3. blocklist in restatements (D2)

class _XmlSource:
    """Filings with synthetic information tables parsed at read time (blocklist applied)."""

    def __init__(self, tables: dict[Filing, list[tuple]]):
        self.tables = tables

    def filings(self, cik, as_of):
        return list(self.tables)

    def rows(self, f):
        return parse.parse_infotable(infotable_xml(self.tables[f]), f.accession_number)


def _f(n, form, date, no=None, kind=None):
    return Filing(cik="1", accession_number=f"0000000001-25-{n:06d}", form_type=form, filing_date=date,
                  period_of_report=P, amendment_no=no, amendment_type=kind)


OVER = ("SYNTH ENERGY PARTNERS", "COM", "90000F106")         # benign as filed in the original
OVER_R = ("SYNTH ENERGY PARTNERS", "COM UNIT", "90000F106")  # same CUSIP; over-matched in the restatement
ORIG = _f(1, "13F-HR", "2025-02-14")
REST = _f(2, "13F-HR/A", "2025-03-03", 1, "RESTATEMENT")
EMPTIED = _f(3, "13F-HR/A", "2025-04-01", 2, "RESTATEMENT")
BLOCK_SRC = _XmlSource({
    ORIG: KEPT[:3] + BLOCKED[:2] + [OVER],
    REST: KEPT[:2] + BLOCKED[2:5] + [OVER_R],
    EMPTIED: BLOCKED[5:9],
})


def _bh(as_of, **kw):
    return tools.call(BLOCK_SRC, "get_holdings_as_of", {"cik": "1", "period": P, "as_of": as_of, **kw})


def test_restatement_rows_are_redacted_and_citation_is_the_restatement():
    out = _bh("2025-03-03")
    assert out["source_accessions"] == [REST.accession_number]
    assert survivors(out["holdings"]) == []
    assert sorted(h["cusip"] for h in out["holdings"]) == sorted(c for _, _, c in KEPT[:2])


def test_over_matched_row_disappears_at_restatement_accepted_cost_d2():
    before, after = _bh("2025-03-02"), _bh("2025-03-03")
    assert OVER[2] in {h["cusip"] for h in before["holdings"]}
    assert OVER[2] not in {h["cusip"] for h in after["holdings"]}  # blocklist, not the §4 resolver


def test_filter_on_blocked_cusip_returns_ok_empty_with_same_citation():
    blocked_cusip = BLOCKED[3][2]
    out = _bh("2025-03-03", cusip=[blocked_cusip])
    assert out["status"] == "ok" and out["holdings"] == []
    assert out["source_accessions"] == [REST.accession_number]


def test_fully_redacted_restatement_still_supersedes_original():
    out = _bh("2025-04-01")
    assert out["status"] == "ok" and out["holdings"] == []
    assert out["accession_number"] == EMPTIED.accession_number and out["source_accessions"] == [EMPTIED.accession_number]


def test_planted_failure_disabled_blocklist_is_detected_in_restatement(monkeypatch):
    from edgar13f import blocklist
    monkeypatch.setattr(blocklist, "is_blocked", lambda *a: False)
    assert len(survivors(_bh("2025-03-03")["holdings"])) == 3  # the check can fail
