"""Addendum A1 (issuer), A2 (max_positions), A3 (list period), A5 (agent mode) and the A0 rule
that the new parameters never change citations. Exact orderings are pinned on an invented
manager (benign made-up issuers and CUSIPs); the A0 sweep runs over every fixture call."""

from __future__ import annotations

import json

import pytest

from edgar13f import DISCLAIMER, server, tools
from edgar13f.rules import Filing
from tests.conftest import FIXTURES
from tests.tools import fixture_golden as fg

P1, P2 = "2024-12-31", "2025-03-31"
A1, B1, B2 = "0000000009-25-000001", "0000000009-25-000002", "0000000009-25-000003"


def _row(acc, name, cusip, value, put_call=None, sh_prn="SH"):
    return {"accession_number": acc, "name_of_issuer": name, "title_of_class": "COM", "cusip": cusip,
            "figi": None, "value": value, "shares_or_principal_amount": value * 10, "sh_prn": sh_prn,
            "put_call": put_call, "investment_discretion": "SOLE", "other_manager": None,
            "voting_authority_sole": 0, "voting_authority_shared": 0, "voting_authority_none": 0}


ROWS = {
    A1: [_row(A1, "ACME WIDGETS CORP", "AAA111111", 100), _row(A1, "BETA TOOLS INC", "BBB222222", 300),
         _row(A1, "OMEGA SHIPPING", "OOO000000", 40)],
    B1: [_row(B1, "ACME  WIDGETS CORP", "AAA111111", 100), _row(B1, "Acme Widgets Corp", "aaa111111", 50),
         _row(B1, "ACME WIDGETS CORP", "AAA111111", 70, "CALL"), _row(B1, "ACME WIDGETS CORP", "AAA111111", 70, "PUT"),
         _row(B1, "BETA TOOLS INC", "BBB222222", 150), _row(B1, "BETA TOOLS INC", "BBB222222", 20, sh_prn="PRN"),
         _row(B1, "GAMMA PAPER CO", "CCC333333", 150), _row(B1, "DELTA FOODS", "DDD444444", 70),
         _row(B1, "DELTA FOODS", "DDD444444", 70, "CALL"), _row(B1, "EPSILON BONDS", "EEE555555", 5, sh_prn="SH"),
         _row(B1, "EPSILON BONDS", "EEE555555", 5, sh_prn="PRN")],
    B2: [_row(B2, "ZETA TEXTILES", "ZZZ999999", 1000), _row(B2, "ACME WIDGETS CORP", "AAA111111", 1)],
}
FILINGS = [
    Filing("9", A1, "13F-HR", "2025-02-14", P1),
    Filing("9", B1, "13F-HR", "2025-05-15", P2),
    Filing("9", B2, "13F-HR/A", "2025-06-02", P2, amendment_no=1, amendment_type="NEW HOLDINGS"),
]


class Invented:
    def filings(self, cik, as_of, periods=None):
        return FILINGS if cik == "9" else None

    def rows(self, f):
        return [dict(r) for r in ROWS[f.accession_number]]


SRC = Invented()
HOLD = {"cik": "9", "period": P2, "as_of": "2025-08-27"}
DIFF = {"cik": "9", "period_a": P1, "period_b": P2, "as_of": "2025-08-27"}
CITES = ("cik", "period", "period_a", "period_b", "as_of", "accession_number", "source_accessions", "filing_date",
         "accession_a", "accession_b", "source_accessions_a", "source_accessions_b")


def call(tool, args, src=SRC):
    out = tools.call(src, tool, args)
    assert out["disclaimer"] == DISCLAIMER
    json.dumps(out)
    return out


def keys(rows):
    out = []
    for r in rows:
        k = (r["cusip"].upper(), r["put_call"], r["sh_prn"])
        if not out or out[-1] != k:
            out.append(k)
    return out


def cites(out):
    return {k: out[k] for k in CITES if k in out}


# A1 issuer

def test_issuer_is_case_insensitive_substring_with_whitespace_collapsed():
    out = call("get_holdings_as_of", {**HOLD, "issuer": "acme   WIDGETS"})
    assert len(out["holdings"]) == 5 and {r["cusip"].upper() for r in out["holdings"]} == {"AAA111111"}
    assert out["matched_cusips"] == ["AAA111111", "aaa111111"]  # distinct as filed, sorted
    assert [k for k in out if k not in cites(out)] == ["status", "disclaimer", "matched_cusips", "holdings"]


@pytest.mark.parametrize("issuer, n", [(" widgets corp", 5), ("widgets corp ", 0), ("CORP", 5), ("zz", 0),
                                       ("Z" * 100, 0), ("ta t", 3)])
def test_issuer_query_whitespace_is_kept_not_stripped(issuer, n):
    assert len(call("get_holdings_as_of", {**HOLD, "issuer": issuer})["holdings"]) == n


def test_issuer_and_cusip_combine_as_and():
    out = call("get_holdings_as_of", {**HOLD, "issuer": "acme", "cusip": ["BBB222222"]})
    assert out["holdings"] == [] and out["matched_cusips"] == []
    out = call("get_holdings_as_of", {**HOLD, "issuer": "acme", "cusip": ["aaa111111", "BBB222222"]})
    assert len(out["holdings"]) == 5


def test_issuer_on_diff_filters_rows_before_consolidation():
    out = call("diff_holdings", {**DIFF, "issuer": "beta"})
    assert out["matched_cusips"] == ["BBB222222"]
    assert {(c["sh_prn"], c["value_a"], c["value_b"]) for c in out["changes"]} == {("SH", 300, 150), ("PRN", 0, 20)}


def test_issuer_without_match_is_ok_and_keeps_citations():
    full, none = call("get_holdings_as_of", HOLD), call("get_holdings_as_of", {**HOLD, "issuer": "no such issuer"})
    assert none["status"] == "ok" and none["holdings"] == [] and none["matched_cusips"] == []
    assert cites(none) == cites(full) and full["source_accessions"] == [B1, B2]


@pytest.mark.parametrize("bad", ["a", "x" * 101, 12, None, ["acme"], ""])
def test_issuer_bad_values_declined(bad):
    for tool, base in (("get_holdings_as_of", HOLD), ("diff_holdings", DIFF)):
        assert call(tool, {**base, "issuer": bad})["reason"] == "invalid_argument"


# A2 max_positions

ORDER_HOLD = [("ZZZ999999", None, "SH"), ("AAA111111", None, "SH"), ("BBB222222", None, "SH"),
              ("CCC333333", None, "SH"), ("AAA111111", "CALL", "SH"), ("AAA111111", "PUT", "SH"),
              ("DDD444444", None, "SH"), ("DDD444444", "CALL", "SH"), ("BBB222222", None, "PRN"),
              ("EEE555555", None, "PRN"), ("EEE555555", None, "SH")]


@pytest.mark.parametrize("k", [1, 2, 3, 5, 6, 10, 11, 200])
def test_holdings_groups_by_summed_value_with_tie_breaks_never_split(k):
    out = call("get_holdings_as_of", {**HOLD, "max_positions": k})
    assert keys(out["holdings"]) == ORDER_HOLD[:k]
    assert (out["total_positions"], out["truncated"], out["order"]) == (11, k < 11, "value_desc")
    want = [r for key in ORDER_HOLD[:k] for f in (B1, B2) for r in ROWS[f]
            if (r["cusip"].upper(), r["put_call"], r["sh_prn"]) == key]
    assert out["holdings"] == want  # every row of each group, as filed, base before supplement
    assert "auto_limited" not in out and cites(out) == cites(call("get_holdings_as_of", HOLD))


ORDER_DIFF = [("ZZZ999999", None, "SH"), ("BBB222222", None, "SH"), ("CCC333333", None, "SH"),
              ("AAA111111", "CALL", "SH"), ("AAA111111", "PUT", "SH"), ("DDD444444", None, "SH"),
              ("DDD444444", "CALL", "SH"), ("AAA111111", None, "SH"), ("OOO000000", None, "SH"),
              ("BBB222222", None, "PRN"), ("EEE555555", None, "PRN"), ("EEE555555", None, "SH")]


@pytest.mark.parametrize("k", [1, 3, 8, 12, 50])
def test_diff_orders_by_abs_value_delta_and_cuts(k):
    out = call("diff_holdings", {**DIFF, "max_positions": k})
    assert [(c["cusip"].upper(), c["put_call"], c["sh_prn"]) for c in out["changes"]] == ORDER_DIFF[:k]
    assert (out["total_positions"], out["truncated"], out["order"]) == (12, k < 12, "abs_value_delta_desc")
    full = {(c["cusip"].upper(), c["put_call"], c["sh_prn"]): c for c in call("diff_holdings", DIFF)["changes"]}
    assert all(c == full[(c["cusip"].upper(), c["put_call"], c["sh_prn"])] for c in out["changes"])
    assert cites(out) == cites(call("diff_holdings", DIFF))


def test_max_positions_counts_after_all_filters():
    out = call("get_holdings_as_of", {**HOLD, "issuer": "acme", "max_positions": 2})
    assert (out["total_positions"], out["truncated"]) == (3, True)
    assert out["matched_cusips"] == ["AAA111111", "aaa111111"]  # the filter's matches, before the cut
    assert keys(out["holdings"]) == [("AAA111111", None, "SH"), ("AAA111111", "CALL", "SH")]
    out = call("diff_holdings", {**DIFF, "cusip": ["eee555555"], "max_positions": 1})
    assert (out["total_positions"], out["truncated"], len(out["changes"])) == (2, True, 1)


@pytest.mark.parametrize("bad", [0, 201, -1, True, False, 1.0, 50.5, "5", None, [5]])
def test_max_positions_bad_values_declined(bad):
    for tool, base in (("get_holdings_as_of", HOLD), ("diff_holdings", DIFF)):
        assert call(tool, {**base, "max_positions": bad})["reason"] == "invalid_argument"


def test_new_arguments_rejected_where_not_defined_and_precedence_kept():
    assert call("list_13f_filings", {"cik": "9", "as_of": "2025-08-27", "issuer": "acme"})["reason"] == \
        "invalid_argument"
    assert call("list_13f_filings", {"cik": "9", "as_of": "2025-08-27", "max_positions": 5})["reason"] == \
        "invalid_argument"
    assert call("get_holdings_as_of", {**HOLD, "period": "2025-03-30", "max_positions": 0})["reason"] == \
        "invalid_argument"
    assert call("get_holdings_as_of", {**HOLD, "period": "2025-03-30", "max_positions": 5})["reason"] == \
        "invalid_period"
    assert call("get_holdings_as_of", {**HOLD, "cik": "8", "issuer": "acme"})["reason"] == "unknown_cik"
    assert call("get_holdings_as_of", {**HOLD, "period": "2025-06-30", "issuer": "acme",
                                       "max_positions": 1})["reason"] == "not_yet_filed"


# A3 period on list_13f_filings

def test_list_period_is_the_full_list_filtered(fixture_source):
    for cik in ("1067983", "1418814", "1894571", "1450709"):
        for as_of in ("2024-11-15", "2025-08-27"):
            full = call("list_13f_filings", {"cik": cik, "as_of": as_of}, fixture_source)
            for period in sorted({f["period_of_report"] for f in full.get("filings", [])} | {"2023-03-31"}):
                got = call("list_13f_filings", {"cik": cik, "as_of": as_of, "period": period}, fixture_source)
                if full["status"] == "declined":
                    assert got == full
                    continue
                assert got == {**full, "filings": [f for f in full["filings"] if f["period_of_report"] == period]}


@pytest.mark.parametrize("args, want", [
    ({"cik": "1067983", "as_of": "2025-08-27", "period": "2025-03-30"}, "invalid_period"),
    ({"cik": "1067983", "as_of": "2025-08-27", "period": "2025-3-31"}, "invalid_argument"),
    ({"cik": "1067983", "as_of": "2025-08-27", "period": 20250331}, "invalid_argument"),
    ({"cik": "x", "as_of": "2025-08-27", "period": "2025-03-30"}, "invalid_argument"),
    ({"cik": "999999999", "as_of": "2025-08-27", "period": "2025-03-31"}, "unknown_cik"),
    ({"cik": "1067983", "as_of": "1999-01-01", "period": "2025-03-31"}, "unknown_cik"),
])
def test_list_period_declines(fixture_source, args, want):
    assert call("list_13f_filings", args, fixture_source)["reason"] == want


# A5 agent mode

def test_agent_mode_limits_unnarrowed_calls(monkeypatch):
    monkeypatch.setenv("EDGAR13F_AGENT_MODE", "on")
    out = call("get_holdings_as_of", HOLD)
    assert (out["total_positions"], out["truncated"], out["order"], out["auto_limited"]) == \
        (11, False, "value_desc", True)
    big = {**ROWS, B1: ROWS[B1] + [_row(B1, f"FILLER {i:03d} CO", f"F{i:08d}", 1) for i in range(60)]}
    monkeypatch.setattr(SRC, "rows", lambda f: [dict(r) for r in big[f.accession_number]], raising=False)
    out = call("get_holdings_as_of", HOLD)
    assert len(keys(out["holdings"])) == 50 and out["truncated"] is True and out["total_positions"] == 71
    out = call("diff_holdings", DIFF)
    assert len(out["changes"]) == 50 and out["auto_limited"] is True and out["order"] == "abs_value_delta_desc"


@pytest.mark.parametrize("extra", [{"cusip": ["AAA111111"]}, {"issuer": "acme"}, {"max_positions": 3}])
def test_agent_mode_leaves_narrowed_calls_alone(monkeypatch, extra):
    plain = {t: call(t, {**b, **extra}) for t, b in (("get_holdings_as_of", HOLD), ("diff_holdings", DIFF))}
    monkeypatch.setenv("EDGAR13F_AGENT_MODE", "on")
    for tool, base in (("get_holdings_as_of", HOLD), ("diff_holdings", DIFF)):
        out = call(tool, {**base, **extra})
        assert out == plain[tool] and "auto_limited" not in out


@pytest.mark.parametrize("value", ["", "ON", "On", " on", "on ", "1", "true", "yes", "off"])
def test_agent_mode_off_unless_exactly_on(monkeypatch, value):
    monkeypatch.setenv("EDGAR13F_AGENT_MODE", value)
    for tool, base in (("get_holdings_as_of", HOLD), ("diff_holdings", DIFF)):
        out = call(tool, base)
        assert not {"auto_limited", "total_positions", "truncated", "order"} & set(out)


def test_agent_mode_does_not_touch_declines_lists_or_find_manager(monkeypatch, fixture_source):
    calls = [("get_holdings_as_of", {**HOLD, "period": "2025-06-30"}), ("get_holdings_as_of", {**HOLD, "cik": "8"}),
             ("diff_holdings", {**DIFF, "period_b": "2024-09-30"}), ("list_13f_filings", {"cik": "9", "as_of": "2025-08-27"})]
    before = [call(t, a) for t, a in calls]
    fm = call("find_manager", {"name": "berkshire"}, fixture_source)
    monkeypatch.setenv("EDGAR13F_AGENT_MODE", "on")
    assert [call(t, a) for t, a in calls] == before
    assert call("find_manager", {"name": "berkshire"}, fixture_source) == fm


# A0 over every fixture call: new parameters only filter or order rows

def _sources():
    from edgar13f.sources import FixtureSource
    return {FIXTURES.name: FixtureSource(FIXTURES), "synthetic": FixtureSource(FIXTURES / "synthetic")}


def test_new_parameters_never_change_citations_on_any_fixture_call(monkeypatch):
    sources, checked = _sources(), 0
    for tag, tool, args in fg.grid():
        if tool == "list_13f_filings" or "cusip" in args or not isinstance(args.get("cik"), str):
            continue
        plain = tools.call(sources[tag], tool, args)
        for extra in ({"max_positions": 1}, {"issuer": "INC"}, {"issuer": "corp", "max_positions": 200}):
            out = tools.call(sources[tag], tool, {**args, **extra})
            assert out["status"] == plain["status"] and out.get("reason") == plain.get("reason")
            assert cites(out) == cites(plain), (tag, tool, args, extra)
            checked += 1
        monkeypatch.setenv("EDGAR13F_AGENT_MODE", "on")
        assert cites(tools.call(sources[tag], tool, args)) == cites(plain)
        monkeypatch.delenv("EDGAR13F_AGENT_MODE")
    assert checked > 2000


def test_agent_mode_on_keeps_v1_bytes_for_calls_it_does_not_apply_to(monkeypatch):
    golden = json.loads((FIXTURES.parent / "golden" / "v1_0_fixture_responses.json").read_text())["responses"]
    monkeypatch.setenv("EDGAR13F_AGENT_MODE", "on")
    sources, n = _sources(), 0
    for i, (tag, tool, args) in enumerate(fg.grid()):
        if tool == "list_13f_filings" or "cusip" in args:
            assert fg.response_hash(sources[tag], tool, args) == golden[i]
            n += 1
    assert n > 1000


def test_structured_content_matches_text_for_new_fields():
    res = server.result_for(SRC, "get_holdings_as_of", {**HOLD, "issuer": "acme", "max_positions": 1})
    assert res.is_error is False and json.loads(res.content[0].text) == res.structured_content


# A6 tool descriptions (not graded): name resolution, narrowing, and what as_of means

def test_tool_descriptions_guide_models():
    from edgar13f.schemas import TOOL_DEFS

    text = json.dumps(TOOL_DEFS)
    assert "with find_manager" in text and "publicly filed" in text
    for tool in ("get_holdings_as_of", "diff_holdings"):
        desc = TOOL_DEFS[tool]["description"]
        assert all(word in desc for word in ("issuer", "cusip", "max_positions", "as_of"))
    assert set(TOOL_DEFS) == set(tools.TOOLS)
