"""Addendum A1, A2, A5: narrowing applied to rows after §4 resolution and redaction.

Nothing here changes which filings are cited (A0); it only filters or orders rows and
changes. A call that uses none of `issuer`, `max_positions` (and, with agent mode off,
nothing else) gets no extra fields, so v1 responses are unchanged.
"""

from __future__ import annotations

import os

from .validate import fold

AGENT_DEFAULT = 50  # A5: max_positions applied in agent mode when the call has no narrowing


def agent_mode() -> bool:
    """A5: on only if $EDGAR13F_AGENT_MODE is exactly "on"."""
    return os.environ.get("EDGAR13F_AGENT_MODE") == "on"


def keep(row: dict, cusips: set | None, issuer: str | None) -> bool:
    """§2 cusip filter AND A1 issuer filter (case-insensitive substring, whitespace collapsed)."""
    if cusips is not None and row["cusip"].upper() not in cusips:
        return False
    return issuer is None or issuer in fold(row["name_of_issuer"])


def _limit(a: dict) -> tuple[int | None, bool]:
    """(max_positions, auto_limited) for a validated get_holdings_as_of / diff_holdings call."""
    if "max_positions" in a:
        return a["max_positions"], False
    if agent_mode() and not ({"cusip", "issuer"} & set(a)):
        return AGENT_DEFAULT, True
    return None, False


def _tiebreak(cusip: str, put_call: str | None, sh_prn: str | None) -> tuple:
    """A2 tie-breaks: cusip ascending, put_call (null first), sh_prn."""
    return cusip, put_call is not None, put_call or "", sh_prn is not None, sh_prn or ""


def _matched(a: dict, rows: list[dict]) -> dict:
    return {"matched_cusips": sorted({r["cusip"] for r in rows})} if "issuer" in a else {}


def _cut(a: dict, ranked: list, order: str, out: dict) -> list:
    k, auto = _limit(a)
    if k is None:
        return ranked
    out.update(total_positions=len(ranked), truncated=len(ranked) > k, order=order)
    if auto:
        out["auto_limited"] = True
    return ranked[:k]


def holdings(a: dict, rows: list[dict]) -> tuple[list[dict], dict]:
    """A2 for get_holdings_as_of: whole consolidation groups by summed value, descending."""
    out = _matched(a, rows)
    if _limit(a)[0] is None:
        return rows, out
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["cusip"].upper(), r["put_call"], r["sh_prn"]), []).append(r)
    ranked = sorted(groups, key=lambda g: (-sum(r["value"] or 0 for r in groups[g]), *_tiebreak(*g)))
    return [r for g in _cut(a, ranked, "value_desc", out) for r in groups[g]], out


def changes(a: dict, rows: list[dict], changed: list[dict]) -> tuple[list[dict], dict]:
    """A2 for diff_holdings: changes by |value_delta|, descending. `rows`: both periods' rows."""
    out = _matched(a, rows)
    if _limit(a)[0] is None:
        return changed, out
    ranked = sorted(changed, key=lambda c: (-abs(c["value_delta"]),
                                            *_tiebreak(c["cusip"].upper(), c["put_call"], c["sh_prn"])))
    return _cut(a, ranked, "abs_value_delta_desc", out), out
