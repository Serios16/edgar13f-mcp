"""Tool behaviour against recorded fixtures (offline)."""

import json

from edgar13f import DISCLAIMER, tools

BRK = "1067983"


def call(src, tool, **args):
    out = tools.call(src, tool, args)
    assert out["disclaimer"] == DISCLAIMER
    json.dumps(out)  # must be JSON-serialisable
    return out


def test_list_filters_by_filing_date_and_sorts(fixture_source):
    out = call(fixture_source, "list_13f_filings", cik="0001067983", as_of="2025-08-13")
    assert out["status"] == "ok" and out["cik"] == BRK
    dates = [(f["filing_date"], f["accession_number"]) for f in out["filings"]]
    assert dates == sorted(dates) and all(d <= "2025-08-13" for d, _ in dates)
    accs = {f["accession_number"] for f in out["filings"]}
    assert "0000950123-25-008361" not in accs
    later = call(fixture_source, "list_13f_filings", cik=BRK, as_of="2025-08-14")
    assert "0000950123-25-008361" in {f["accession_number"] for f in later["filings"]}


def test_berkshire_new_holdings_supplement_appears_on_filing_date(fixture_source):
    before = call(fixture_source, "get_holdings_as_of", cik=BRK, period="2025-03-31", as_of="2025-08-13")
    after = call(fixture_source, "get_holdings_as_of", cik=BRK, period="2025-03-31", as_of="2025-08-14")
    assert before["source_accessions"] == ["0000950123-25-005701"]
    assert after["accession_number"] == "0000950123-25-005701"
    assert after["filing_date"] == "2025-05-15"
    assert after["source_accessions"] == ["0000950123-25-005701", "0000950123-25-008361"]
    assert len(after["holdings"]) > len(before["holdings"])
    assert {h["accession_number"] for h in after["holdings"]} == set(after["source_accessions"])


def test_restatement_replaces_original(fixture_source):
    args = dict(cik="1894571", period="2024-03-31")
    orig = call(fixture_source, "get_holdings_as_of", as_of="2024-11-14", **args)
    rest = call(fixture_source, "get_holdings_as_of", as_of="2024-11-15", **args)
    assert orig["source_accessions"] == ["0001894571-24-000003"]
    assert rest["source_accessions"] == ["0001894571-24-000008"]
    assert rest["filing_date"] == "2024-11-15"
    assert {h["accession_number"] for h in rest["holdings"]} <= {"0001894571-24-000008"}


def test_combination_report_with_new_holdings(fixture_source):
    out = call(fixture_source, "get_holdings_as_of", cik="1418814", period="2024-09-30", as_of="2025-01-01")
    assert out["source_accessions"] == ["0001418812-24-000021", "0001418812-24-000022"]


def test_row_shape(fixture_source):
    out = call(fixture_source, "get_holdings_as_of", cik=BRK, period="2024-12-31", as_of="2025-03-01")
    row = out["holdings"][0]
    for key in ("accession_number", "name_of_issuer", "title_of_class", "cusip", "figi", "value",
                "shares_or_principal_amount", "sh_prn", "put_call", "investment_discretion", "other_manager",
                "voting_authority_sole", "voting_authority_shared", "voting_authority_none"):
        assert key in row
    assert all(isinstance(h["value"], int) and isinstance(h["shares_or_principal_amount"], int)
               for h in out["holdings"])
    assert all(h["sh_prn"] in ("SH", "PRN") and h["put_call"] in (None, "PUT", "CALL") for h in out["holdings"])


def test_cusip_filter_is_case_insensitive_and_keeps_citations(fixture_source):
    full = call(fixture_source, "get_holdings_as_of", cik=BRK, period="2024-12-31", as_of="2025-03-01")
    cusip = full["holdings"][0]["cusip"]
    sub = call(fixture_source, "get_holdings_as_of", cik=BRK, period="2024-12-31", as_of="2025-03-01",
               cusip=[cusip.lower()])
    assert sub["holdings"] and all(h["cusip"].upper() == cusip.upper() for h in sub["holdings"])
    assert {k: v for k, v in sub.items() if k != "holdings"} == {k: v for k, v in full.items() if k != "holdings"}


def test_declines(fixture_source):
    def reason(tool, **a):
        out = call(fixture_source, tool, **a)
        assert out["status"] == "declined" and "holdings" not in out and isinstance(out["message"], str)
        return out["reason"]

    assert reason("list_13f_filings", cik="999999999", as_of="2025-01-01") == "unknown_cik"
    assert reason("list_13f_filings", cik="2037077", as_of="2024-11-13") == "unknown_cik"
    assert reason("get_holdings_as_of", cik="1450709", period="2024-09-30", as_of="2025-01-01") == "notice_only"
    assert reason("get_holdings_as_of", cik="1450709", period="2024-09-30", as_of="2024-11-14") == "not_yet_filed"
    assert reason("get_holdings_as_of", cik=BRK, period="2025-06-30", as_of="2025-06-30") == "not_yet_filed"
    assert reason("get_holdings_as_of", cik=BRK, period="2025-09-30", as_of="2025-08-27") == "not_yet_filed"
    assert reason("diff_holdings", cik=BRK, period_a="2025-03-31", period_b="2025-06-30",
                  as_of="2025-08-13") == "not_yet_filed"
    assert reason("diff_holdings", cik="1450709", period_a="2024-06-30", period_b="2025-09-30",
                  as_of="2025-08-27") == "notice_only"


def test_diff_consolidates_and_classifies(fixture_source):
    out = call(fixture_source, "diff_holdings", cik=BRK, period_a="2024-12-31", period_b="2025-03-31",
               as_of="2025-08-27")
    assert out["source_accessions_b"] == ["0000950123-25-005701", "0000950123-25-008361"]
    keys = [(c["cusip"].upper(), c["put_call"], c["sh_prn"]) for c in out["changes"]]
    assert len(keys) == len(set(keys))
    for c in out["changes"]:
        assert c["shares_delta"] == c["shares_b"] - c["shares_a"]
        assert c["value_delta"] == c["value_b"] - c["value_a"]
        if c["change_type"] == "added":
            assert c["shares_a"] == 0 and c["value_a"] == 0
        if c["change_type"] == "removed":
            assert c["shares_b"] == 0 and c["value_b"] == 0
    hold_b = call(fixture_source, "get_holdings_as_of", cik=BRK, period="2025-03-31", as_of="2025-08-27")
    one = out["changes"][0]
    total = sum(h["shares_or_principal_amount"] for h in hold_b["holdings"]
                if h["cusip"].upper() == one["cusip"].upper() and h["put_call"] == one["put_call"]
                and h["sh_prn"] == one["sh_prn"])
    assert total == one["shares_b"]
    filt = call(fixture_source, "diff_holdings", cik=BRK, period_a="2024-12-31", period_b="2025-03-31",
                as_of="2025-08-27", cusip=[one["cusip"]])
    assert [c["cusip"] for c in filt["changes"]] == [one["cusip"]]
    assert filt["accession_a"] == out["accession_a"] and filt["source_accessions_b"] == out["source_accessions_b"]
