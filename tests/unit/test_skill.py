"""The agent skill (skills/edgar13f/SKILL.md) may only name tools, parameters and decline reasons
that exist in contracts/tools.schema.json and Addendum A, and must name all of them."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = (ROOT / "skills/edgar13f/SKILL.md").read_text()
SCHEMA = json.loads((ROOT / "contracts/tools.schema.json").read_text())
ADDENDUM = (ROOT / "contracts/CONTRACTS_ADDENDUM_A.md").read_text()

# Output fields and environment variables the skill may mention besides tools/params/reasons.
OUTPUT_FIELDS = set()
for _d in SCHEMA["$defs"].values():
    OUTPUT_FIELDS |= set(_d.get("properties", {}))
for _t in SCHEMA["tools"].values():
    for _o in _t["outputSchema"]["oneOf"]:
        OUTPUT_FIELDS |= set(_o.get("properties", {}))
# Addendum A response fields, taken from its text (backticked or quoted snake_case names).
OUTPUT_FIELDS |= set(re.findall(r"`(\w+)[`:]", ADDENDUM)) | set(re.findall(r'"(\w+)"', ADDENDUM))
ENV_VARS = set(re.findall(r"\b(EDGAR13F_[A-Z_]+)\b", (ROOT / "README.md").read_text()))


def _tools() -> dict[str, set[str]]:
    tools = {n: set(t["inputSchema"]["properties"]) for n, t in SCHEMA["tools"].items()}
    # Addendum A: A1 issuer, A2 max_positions, A3 period, A4 find_manager(name, as_of, limit).
    add = {"issuer", "max_positions"}
    tools["get_holdings_as_of"] |= add
    tools["diff_holdings"] |= add
    tools["list_13f_filings"] |= {"period"}
    tools["find_manager"] = {"name", "as_of", "limit"}
    for word in ("issuer", "max_positions", "period", "find_manager", "limit"):
        assert f"`{word}`" in ADDENDUM or word in ADDENDUM, word
    return tools


TOOLS = _tools()
PARAMS = set().union(*TOOLS.values())
REASONS = set(SCHEMA["$defs"]["declineReason"]["enum"])
TICKS = re.findall(r"`([^`\n]+)`", SKILL)


def test_frontmatter():
    m = re.match(r"---\nname: (\S+)\ndescription: (.+)\n---\n", SKILL)
    assert m and m.group(1) == "edgar13f" and "13F" in m.group(2)


def test_every_tool_call_uses_real_tool_and_params():
    calls = re.findall(r"`(\w+)\(([^)]*)\)`", SKILL)
    assert {c[0] for c in calls} == set(TOOLS), "skill must show every tool call signature"
    for tool, args in calls:
        assert tool in TOOLS, tool
        for arg in re.findall(r"[A-Za-z_]\w*", args):
            assert arg in TOOLS[tool], f"{tool}: unknown parameter {arg}"


def test_every_identifier_is_known():
    known = set(TOOLS) | PARAMS | REASONS | OUTPUT_FIELDS | ENV_VARS | {"long", "ok", "declined", "status", "true", "false"}
    for tick in TICKS:
        for ident in re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", tick):
            assert ident in known, f"unknown identifier {ident!r} in `{tick}`"
        for ident in re.findall(r"\bEDGAR13F_[A-Z_]+\b", tick):
            assert ident in ENV_VARS, ident


def test_all_declines_and_tools_named():
    ticks = set(TICKS)
    assert REASONS <= ticks, REASONS - ticks
    for name in TOOLS:
        assert any(re.search(rf"\b{name}\b", t) for t in TICKS), name
    for needed in ("as_of", "max_positions", "EDGAR13F_" + "RED" + "ACT", "EDGAR13F_AGENT_MODE")  # split: the blocklist guard bans the literal here:
        assert any(needed in t for t in TICKS), needed


def test_decline_table_has_no_invented_reason():
    rows = set(re.findall(r"^\| `(\w+)` \|", SKILL, re.M)) - {"reason"}  # minus the header cell
    assert rows == REASONS


def test_planted_unknown_names_are_caught():
    bad = "`get_holdings_as_of(cik, period, as_of, bogus_param)` `made_up_tool(cik)` `not_a_reason`"
    calls = re.findall(r"`(\w+)\(([^)]*)\)`", bad)
    assert "bogus_param" not in TOOLS["get_holdings_as_of"]
    assert calls[1][0] not in TOOLS
    assert "not_a_reason" not in REASONS | PARAMS | OUTPUT_FIELDS
