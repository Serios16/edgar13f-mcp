"""Leakage invariant suite with mutant and no-op controls."""

from edgar13f import rules

from .leakage import run_suite

MIN_CASES = 100


def test_suite_passes_on_real_rules():
    n, violations = run_suite()
    assert n >= MIN_CASES, n
    assert violations == [], violations[:5]


def test_mutant_control_as_of_filter_disabled_reports_violations(monkeypatch):
    monkeypatch.setattr(rules, "visible", lambda filing, as_of: True)
    n, violations = run_suite()
    assert n >= MIN_CASES
    assert len(violations) >= 1


def test_noop_control_passes(monkeypatch):
    original = rules.visible
    monkeypatch.setattr(rules, "visible", lambda filing, as_of: original(filing, as_of))
    n, violations = run_suite()
    assert n >= MIN_CASES
    assert violations == []
