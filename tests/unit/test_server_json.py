"""Stage 5 (c): server.json stays consistent with the package (offline; nothing is published).

The full schema check (static.modelcontextprotocol.io 2025-12-11) and `mcp-publisher validate` were run
once by hand (`reports/artifacts/server_json_validation_stage5.txt`); this test pins the rules from the
registry docs that the repository itself can break: name pattern and README `mcp-name:` marker (PyPI
ownership), description length, one version everywhere, PyPI + stdio, advertised variables.
"""

from __future__ import annotations

import copy
import json
import re
import tomllib

import edgar13f
from tests.conftest import REPO

SCHEMA = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
NAME = re.compile(r"^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$")  # ServerDetail.name pattern in that schema
NEVER_ADVERTISED = {"EDGAR13F_REDACT", "EDGAR13F_FIXTURE_DIR"}  # rule 2 switch; test hook


def problems(server: dict, readme: str, version: str) -> list[str]:
    out = []
    pkg = (server.get("packages") or [{}])[0]
    if server.get("$schema") != SCHEMA:
        out.append("$schema is not the 2025-12-11 schema")
    name = server.get("name", "")
    if not NAME.match(name) or not name.startswith("io.github.") or len(name) > 200:
        out.append(f"name {name!r} breaks the pattern or the io.github namespace")
    markers = re.findall(r"mcp-name:\s*(\S+?)(?=\s|-->|<|$)", readme)
    if markers != [name]:
        out.append(f"README mcp-name markers {markers} != [{name!r}]")
    if not 1 <= len(server.get("description", "")) <= 100:
        out.append("description must be 1-100 characters")
    if not (server.get("version") == pkg.get("version") == version == edgar13f.__version__):
        out.append(f"versions differ: {server.get('version')}, {pkg.get('version')}, {version}, {edgar13f.__version__}")
    if (pkg.get("registryType"), pkg.get("registryBaseUrl"), pkg.get("transport")) != (
            "pypi", "https://pypi.org", {"type": "stdio"}):
        out.append("package must be PyPI (https://pypi.org) over stdio")
    names = {v["name"] for v in pkg.get("environmentVariables", [])}
    if "SEC_USER_AGENT" not in names or names & NEVER_ADVERTISED:
        out.append(f"advertised variables {sorted(names)}")
    out += [f"{n} not documented in README" for n in sorted(names) if n not in readme]
    return out


def _inputs():
    server = json.loads((REPO / "server.json").read_text())
    readme = (REPO / "README.md").read_text()
    version = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["version"]
    return server, readme, version


def test_server_json_is_consistent():
    assert problems(*_inputs()) == []


def test_planted_inconsistencies_are_caught():
    server, readme, version = _inputs()
    plants = {
        "long description": lambda s: s.update(description="x" * 101),
        "version drift": lambda s: s.update(version="9.9.9"),
        "other namespace": lambda s: s.update(name="com.example/edgar13f-mcp"),
        "redaction switch advertised": lambda s: s["packages"][0]["environmentVariables"].append(
            {"name": "EDGAR13F_REDACT", "description": "x"}),
        "http transport": lambda s: s["packages"][0].update(transport={"type": "streamable-http"}),
    }
    for label, plant in plants.items():
        mutated = copy.deepcopy(server)
        plant(mutated)
        assert problems(mutated, readme, version), label
    assert problems(server, readme.replace("mcp-name:", "mcp_name:"), version), "missing README marker"
