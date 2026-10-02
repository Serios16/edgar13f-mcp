"""Leakage invariant suite with mutant and no-op controls (v1 tools, Addendum A parameters and
find_manager(as_of)); the mutant control must find violations in every category."""

from edgar13f import rules

from .leakage import categories, run_suite

MIN_CASES = 100
CATEGORIES = {"list", "list_period", "holdings", "holdings_issuer", "holdings_max", "holdings_agent", "diff",
              "diff_narrowed", "find_manager"}


def test_suite_passes_on_real_rules():
    stats: dict = {}
    n, violations = run_suite(stats=stats)
    assert n >= MIN_CASES, n
    assert violations == [], violations[:5]
    assert set(stats) == CATEGORIES and min(stats.values()) >= 100, stats


def test_mutant_control_as_of_filter_disabled_reports_violations(monkeypatch):
    monkeypatch.setattr(rules, "visible", lambda filing, as_of: True)
    n, violations = run_suite()
    assert n >= MIN_CASES
    assert len(violations) >= 1
    assert categories(violations) == CATEGORIES  # every category, the new ones included, can fail


def test_noop_control_passes(monkeypatch):
    original = rules.visible
    monkeypatch.setattr(rules, "visible", lambda filing, as_of: original(filing, as_of))
    n, violations = run_suite()
    assert n >= MIN_CASES
    assert violations == []
