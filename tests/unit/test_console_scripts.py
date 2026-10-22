"""Stage 6 (P16): `edgar13f-mcp` (what `uvx edgar13f-mcp` runs for registry clients) and `edgar13f-server`
are two names for the same function, both declared in pyproject.toml and in the installed metadata."""

from __future__ import annotations

import importlib
import importlib.metadata as md
import tomllib

from tests.conftest import REPO

NAMES = ("edgar13f-mcp", "edgar13f-server")


def _resolve(target: str):
    module, _, attr = target.partition(":")
    return getattr(importlib.import_module(module), attr)


def test_both_console_scripts_are_declared_and_point_to_the_same_function():
    scripts = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["scripts"]
    assert sorted(scripts) == sorted(NAMES)
    assert set(scripts.values()) == {"edgar13f.server:main"}
    from edgar13f import server
    assert _resolve(scripts["edgar13f-mcp"]) is _resolve(scripts["edgar13f-server"]) is server.main


def test_installed_metadata_carries_both_entry_points():
    found = {e.name: e.value for e in md.entry_points(group="console_scripts") if e.name in NAMES}
    assert found == {n: "edgar13f.server:main" for n in NAMES}
