"""Tool input schemas advertised over MCP (inlined from contracts/tools.schema.json v1.0)."""

from __future__ import annotations

_CIK = {"type": "string", "pattern": "^[0-9]{1,10}$", "description": "SEC Central Index Key; leading zeros optional."}
_DATE = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$", "description": "ISO-8601 date; knowledge date."}
_QEND = {
    "type": "string",
    "pattern": "^[0-9]{4}-(03-31|06-30|09-30|12-31)$",
    "description": "Form 13F report period: a calendar quarter-end date.",
}
_CUSIPS = {
    "type": "array",
    "items": {"type": "string", "pattern": "^[0-9A-Za-z]{9}$"},
    "minItems": 1,
    "maxItems": 50,
    "uniqueItems": True,
}

TOOL_DEFS = {
    "list_13f_filings": {
        "description": "Every Form 13F submission (13F-HR, 13F-HR/A, 13F-NT, 13F-NT/A) by the manager "
        "whose EDGAR filing date is on or before as_of.",
        "inputSchema": {
            "type": "object",
            "required": ["cik", "as_of"],
            "properties": {"cik": _CIK, "as_of": _DATE},
            "additionalProperties": False,
        },
    },
    "get_holdings_as_of": {
        "description": "Effective 13F holdings of the manager for one report period as knowable on as_of "
        "(point-in-time and amendment rules), with the accession number(s) they come from.",
        "inputSchema": {
            "type": "object",
            "required": ["cik", "period", "as_of"],
            "properties": {
                "cik": _CIK,
                "period": _QEND,
                "as_of": _DATE,
                "cusip": _CUSIPS,
                "position_type": {
                    "type": "string",
                    "enum": ["long"],
                    "default": "long",
                    "description": "Form 13F contains long positions only; any other value is declined "
                    "with unsupported_request.",
                },
            },
            "additionalProperties": False,
        },
    },
    "diff_holdings": {
        "description": "Position-level changes between period_a and period_b, each computed with "
        "get_holdings_as_of rules on the same as_of and consolidated by (cusip, put_call, sh_prn).",
        "inputSchema": {
            "type": "object",
            "required": ["cik", "period_a", "period_b", "as_of"],
            "properties": {"cik": _CIK, "period_a": _QEND, "period_b": _QEND, "as_of": _DATE, "cusip": _CUSIPS},
            "additionalProperties": False,
        },
    },
}
