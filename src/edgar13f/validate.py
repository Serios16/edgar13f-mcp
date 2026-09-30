"""Argument validation (CONTRACTS §2 and §6 precedence).

Each validator returns (normalized_args, None) or (None, Decline). Checks run in
precedence order: invalid_argument > invalid_period > unsupported_request; the
data-dependent reasons (unknown_cik, notice_only, not_yet_filed) come later.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

_CIK = re.compile(r"^[0-9]{1,10}$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_CUSIP = re.compile(r"^[0-9A-Za-z]{9}$")
QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")

ALLOWED = {
    "list_13f_filings": ({"cik", "as_of"}, set()),
    "get_holdings_as_of": ({"cik", "period", "as_of"}, {"cusip", "position_type"}),
    "diff_holdings": ({"cik", "period_a", "period_b", "as_of"}, {"cusip"}),
}


@dataclass(frozen=True)
class Decline:
    reason: str
    message: str


def _date_ok(value: object) -> bool:
    if not isinstance(value, str) or not _DATE.match(value):
        return False
    try:
        dt.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate(tool: str, args: object) -> tuple[dict | None, Decline | None]:
    required, optional = ALLOWED[tool]
    if not isinstance(args, dict):
        return None, Decline("invalid_argument", "arguments must be a JSON object")
    unknown = sorted(set(args) - required - optional)
    if unknown:
        return None, Decline("invalid_argument", f"unknown argument(s): {', '.join(unknown)}")
    missing = sorted(required - set(args))
    if missing:
        return None, Decline("invalid_argument", f"missing argument(s): {', '.join(missing)}")
    cik = args["cik"]
    if not isinstance(cik, str) or not _CIK.match(cik):
        return None, Decline("invalid_argument", "cik must be a string of 1-10 ASCII digits")
    dates = [k for k in ("as_of", "period", "period_a", "period_b") if k in args]
    for key in dates:
        if not _date_ok(args[key]):
            return None, Decline("invalid_argument", f"{key} must be a valid YYYY-MM-DD date")
    if "cusip" in args:
        cusips = args["cusip"]
        if (
            not isinstance(cusips, list)
            or not 1 <= len(cusips) <= 50
            or not all(isinstance(c, str) and _CUSIP.match(c) for c in cusips)
            or len(set(cusips)) != len(cusips)
        ):
            return None, Decline("invalid_argument", "cusip must be an array of 1-50 unique 9-character CUSIPs")
    if "position_type" in args and not isinstance(args["position_type"], str):
        return None, Decline("invalid_argument", "position_type must be a string")
    for key in ("period", "period_a", "period_b"):
        if key in args and args[key][5:] not in QUARTER_ENDS:
            return None, Decline("invalid_period", f"{key} must be a calendar quarter end")
    if tool == "diff_holdings" and args["period_b"] <= args["period_a"]:
        return None, Decline("invalid_period", "period_b must be after period_a")
    if args.get("position_type", "long") != "long":
        return None, Decline("unsupported_request", "Form 13F reports long positions only")
    norm = dict(args)
    norm["cik"] = str(int(cik))
    if "cusip" in args:
        norm["cusip"] = {c.upper() for c in args["cusip"]}
    return norm, None
