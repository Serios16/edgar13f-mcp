"""Tool input schemas advertised over MCP (inlined from contracts/tools.schema.json v1.0, plus
Addendum A parameters and find_manager). Descriptions follow A6 (not graded)."""

from __future__ import annotations

_CIK = {"type": "string", "pattern": "^[0-9]{1,10}$", "description": "SEC Central Index Key; leading zeros optional. "
        "Resolve a manager's name to its CIK with find_manager."}
_DATE = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
         "description": "ISO-8601 knowledge date: the answer uses only what was publicly filed on EDGAR by this date."}
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
_ISSUER = {"type": "string", "minLength": 2, "maxLength": 100,
           "description": "Keep only rows whose name_of_issuer contains this text (case-insensitive, whitespace "
           "collapsed); combined with cusip as AND. The response lists matched_cusips."}
_MAX = {"type": "integer", "minimum": 1, "maximum": 200,
        "description": "Return only the largest positions (by value); the response adds total_positions, "
        "truncated and order."}
_NARROW = (" Large managers file tens of thousands of rows: narrow with issuer, cusip or max_positions. "
           "as_of means what was publicly filed by that date.")

TOOL_DEFS = {
    "find_manager": {
        "description": "Find a manager's CIK from its name (a case-insensitive substring of current or former "
        "EDGAR entity names). Candidates that have filed Form 13F come first. Use it before the other tools "
        "when you only know the name. entity_name is EDGAR's current name (not point-in-time); with as_of, "
        "has_13f_filings counts only 13F filings dated on or before as_of.",
        "inputSchema": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string", "minLength": 3, "maxLength": 100},
                "as_of": _DATE,
                "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 10},
            },
            "additionalProperties": False,
        },
    },
    "list_13f_filings": {
        "description": "Every Form 13F submission (13F-HR, 13F-HR/A, 13F-NT, 13F-NT/A) by the manager "
        "whose EDGAR filing date is on or before as_of (what was publicly filed by then). Pass period to list "
        "only the filings for one report period.",
        "inputSchema": {
            "type": "object",
            "required": ["cik", "as_of"],
            "properties": {"cik": _CIK, "as_of": _DATE, "period": _QEND},
            "additionalProperties": False,
        },
    },
    "get_holdings_as_of": {
        "description": "Effective 13F holdings of the manager for one report period as knowable on as_of "
        "(point-in-time and amendment rules), with the accession number(s) they come from." + _NARROW,
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
                "issuer": _ISSUER,
                "max_positions": _MAX,
            },
            "additionalProperties": False,
        },
    },
    "diff_holdings": {
        "description": "Position-level changes between period_a and period_b, each computed with "
        "get_holdings_as_of rules on the same as_of and consolidated by (cusip, put_call, sh_prn)." + _NARROW,
        "inputSchema": {
            "type": "object",
            "required": ["cik", "period_a", "period_b", "as_of"],
            "properties": {"cik": _CIK, "period_a": _QEND, "period_b": _QEND, "as_of": _DATE, "cusip": _CUSIPS,
                           "issuer": _ISSUER, "max_positions": _MAX},
            "additionalProperties": False,
        },
    },
}
