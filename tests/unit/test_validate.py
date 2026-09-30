import pytest

from edgar13f import DISCLAIMER, tools

BRK = "1067983"


def reason(src, tool, args):
    out = tools.call(src, tool, args)
    assert out["disclaimer"] == DISCLAIMER
    return out.get("reason")


@pytest.mark.parametrize("args,expected", [
    ({"cik": BRK, "as_of": "2025-01-01", "bogus": 1}, "invalid_argument"),
    ({"cik": BRK}, "invalid_argument"),
    ({"cik": 1067983, "as_of": "2025-01-01"}, "invalid_argument"),
    ({"cik": "12345678901", "as_of": "2025-01-01"}, "invalid_argument"),
    ({"cik": "10a", "as_of": "2025-01-01"}, "invalid_argument"),
    ({"cik": BRK, "as_of": "2025-02-30"}, "invalid_argument"),
    ({"cik": BRK, "as_of": "20250101"}, "invalid_argument"),
    ({"cik": "９９", "as_of": "2025-01-01"}, "invalid_argument"),
])
def test_list_invalid_argument(fixture_source, args, expected):
    assert reason(fixture_source, "list_13f_filings", args) == expected


@pytest.mark.parametrize("extra,expected", [
    ({"period": "2024-12-30"}, "invalid_period"),
    ({"period": "2024-13-31"}, "invalid_argument"),
    ({"position_type": "short"}, "unsupported_request"),
    ({"position_type": "LONG"}, "unsupported_request"),
    ({"position_type": None}, "invalid_argument"),
    ({"cusip": []}, "invalid_argument"),
    ({"cusip": ["12345678"]}, "invalid_argument"),
    ({"cusip": ["037833100", "037833100"]}, "invalid_argument"),
    ({"cusip": "037833100"}, "invalid_argument"),
    ({"cusip": ["0"] * 0 + [f"{i:09d}" for i in range(51)]}, "invalid_argument"),
    # precedence: invalid_argument > invalid_period > unsupported_request > unknown_cik
    ({"period": "2024-12-30", "bogus": True}, "invalid_argument"),
    ({"period": "2024-12-30", "position_type": "short"}, "invalid_period"),
])
def test_holdings_declines(fixture_source, extra, expected):
    args = {"cik": BRK, "period": "2024-12-31", "as_of": "2025-03-01", **extra}
    assert reason(fixture_source, "get_holdings_as_of", args) == expected


def test_unsupported_beats_unknown_cik(fixture_source):
    args = {"cik": "999999999", "period": "2024-12-31", "as_of": "2025-03-01", "position_type": "short"}
    assert reason(fixture_source, "get_holdings_as_of", args) == "unsupported_request"


@pytest.mark.parametrize("pa,pb,expected", [
    ("2024-12-31", "2024-12-31", "invalid_period"),
    ("2025-03-31", "2024-12-31", "invalid_period"),
    ("2024-12-15", "2025-03-31", "invalid_period"),
])
def test_diff_invalid_period(fixture_source, pa, pb, expected):
    args = {"cik": BRK, "period_a": pa, "period_b": pb, "as_of": "2025-08-01"}
    assert reason(fixture_source, "diff_holdings", args) == expected


def test_diff_rejects_position_type(fixture_source):
    args = {"cik": BRK, "period_a": "2024-09-30", "period_b": "2024-12-31", "as_of": "2025-08-01",
            "position_type": "long"}
    assert reason(fixture_source, "diff_holdings", args) == "invalid_argument"


def test_none_arguments_declined(fixture_source):
    assert reason(fixture_source, "list_13f_filings", None) == "invalid_argument"
