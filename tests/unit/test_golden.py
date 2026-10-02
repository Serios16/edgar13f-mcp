"""Stage 3 (a): with EDGAR13F_REDACT unset, every tool response over every recorded and
synthetic fixture is byte-identical to v1.0.0. The golden was written by the v1.0.0 source
(`tests/tools/fixture_golden.py`); it holds hashes only."""

import json
from collections import Counter

from edgar13f import tools
from edgar13f.sources import FixtureSource
from tests.conftest import FIXTURES, REPO
from tests.tools import fixture_golden as fg

GOLDEN = REPO / "tests" / "golden" / "v1_0_fixture_responses.json"


def _golden() -> dict:
    return json.loads(GOLDEN.read_text())


def test_grid_is_the_one_the_golden_was_written_for():
    golden, items = _golden(), fg.grid()
    assert golden["written_by"].startswith("v1.0.0")
    assert len(items) == golden["calls"] == len(golden["responses"])
    assert fg.grid_digest(items) == golden["grid_sha256"]


def test_grid_covers_every_outcome():
    sources = {FIXTURES.name: FixtureSource(FIXTURES), "synthetic": FixtureSource(FIXTURES / "synthetic")}
    seen = Counter()
    for tag, tool, args in fg.grid():
        out = tools.call(sources[tag], tool, args)
        seen[(tool, out.get("reason") or out["status"])] += 1
    assert seen[("get_holdings_as_of", "ok")] >= 500 and seen[("diff_holdings", "ok")] >= 100
    assert seen[("list_13f_filings", "ok")] >= 1000
    for reason in ("unknown_cik", "not_yet_filed", "notice_only", "invalid_period", "invalid_argument",
                   "unsupported_request"):
        assert any(r == reason for (_, r) in seen), reason


def test_responses_byte_identical_to_v1_0_with_switch_unset():
    got, want = fg.compute(fg.grid()), _golden()["responses"]
    assert [i for i, (a, b) in enumerate(zip(got, want)) if a != b] == []


def test_planted_one_character_change_is_detected(monkeypatch):
    monkeypatch.setattr(tools, "DISCLAIMER", tools.DISCLAIMER + " ")
    got, want = fg.compute(fg.grid()[:40]), _golden()["responses"][:40]
    assert all(a != b for a, b in zip(got, want))
