from edgar13f import rules
from edgar13f.rules import Filing

P = "2024-12-31"


def F(acc, form, date, period=P, no=None, kind=None):
    return Filing(cik="1", accession_number=acc, form_type=form, filing_date=date,
                  period_of_report=period, amendment_no=no, amendment_type=kind)


def accs(res):
    base, sup = res
    return base.accession_number, [s.accession_number for s in sup]


def test_visible_is_inclusive_of_filing_date():
    f = F("0000000001-25-000001", "13F-HR", "2025-02-14")
    assert rules.visible(f, "2025-02-14")
    assert not rules.visible(f, "2025-02-13")


def test_original_only():
    fs = [F("0000000001-25-000001", "13F-HR", "2025-02-14")]
    assert accs(rules.resolve(fs, P, "2025-02-14")) == ("0000000001-25-000001", [])
    assert rules.resolve(fs, P, "2025-02-13") == "not_yet_filed"


def test_restatement_supersedes_everything_before_it():
    fs = [
        F("0000000001-25-000001", "13F-HR", "2025-02-14"),
        F("0000000001-25-000002", "13F-HR/A", "2025-02-20", no=1, kind="NEW HOLDINGS"),
        F("0000000001-25-000003", "13F-HR/A", "2025-03-01", no=2, kind="RESTATEMENT"),
        F("0000000001-25-000004", "13F-HR/A", "2025-03-05", no=3, kind="NEW HOLDINGS"),
    ]
    assert accs(rules.resolve(fs, P, "2025-02-25")) == ("0000000001-25-000001", ["0000000001-25-000002"])
    assert accs(rules.resolve(fs, P, "2025-03-01")) == ("0000000001-25-000003", [])
    assert accs(rules.resolve(fs, P, "2025-03-10")) == ("0000000001-25-000003", ["0000000001-25-000004"])


def test_same_day_order_amendment_no_nulls_first_then_accession():
    fs = [
        F("0000000009-25-000009", "13F-HR/A", "2025-02-14", no=1, kind="NEW HOLDINGS"),
        F("0000000005-25-000005", "13F-HR", "2025-02-14"),
        F("0000000001-25-000001", "13F-HR/A", "2025-02-14", no=2, kind="RESTATEMENT"),
    ]
    # order: original (null no), NH (no=1), RESTATEMENT (no=2) -> base is the restatement
    assert accs(rules.resolve(fs, P, "2025-02-14")) == ("0000000001-25-000001", [])


def test_unspecified_amendment_treated_as_restatement():
    fs = [
        F("0000000001-25-000001", "13F-HR", "2025-02-14"),
        F("0000000001-25-000002", "13F-HR/A", "2025-02-20", no=1, kind=None),
    ]
    assert accs(rules.resolve(fs, P, "2025-02-20")) == ("0000000001-25-000002", [])


def test_other_periods_and_notices():
    fs = [
        F("0000000001-25-000001", "13F-HR", "2025-02-14", period="2024-09-30"),
        F("0000000001-25-000002", "13F-NT", "2025-02-14"),
    ]
    assert rules.resolve(fs, P, "2025-02-14") == "notice_only"
    assert rules.resolve(fs, P, "2025-02-13") == "not_yet_filed"
    fs.append(F("0000000001-25-000003", "13F-HR", "2025-02-15"))
    assert accs(rules.resolve(fs, P, "2025-02-15")) == ("0000000001-25-000003", [])


def test_new_holdings_without_base_is_declined():
    fs = [F("0000000001-25-000002", "13F-HR/A", "2025-02-20", no=1, kind="NEW HOLDINGS")]
    assert rules.resolve(fs, P, "2025-03-01") == "not_yet_filed"


def test_filing_record_shape():
    f = Filing(cik="1067983", accession_number="0000950123-25-001234", form_type="13F-HR/A",
               filing_date="2025-02-14", period_of_report=P, amendment_no=1, amendment_type="RESTATEMENT")
    rec = f.record()
    assert rec["is_amendment"] is True
    assert rec["edgar_url"] == ("https://www.sec.gov/Archives/edgar/data/1067983/"
                                "000095012325001234/0000950123-25-001234-index.htm")
    assert set(rec) == {"accession_number", "form_type", "filing_date", "period_of_report", "is_amendment",
                        "amendment_no", "amendment_type", "report_type", "filing_manager_name", "edgar_url"}
