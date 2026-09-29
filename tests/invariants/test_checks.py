"""Planted-failure tests: every CI check must be able to fail."""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tests.checks import claims_check, map_check, size_budget
from tests.conftest import REPO, NetworkBlocked


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_repo_passes_all_static_checks():
    assert size_budget.check(REPO) == []
    assert map_check.check(REPO) == []
    assert claims_check.check(REPO) == []


def test_size_budget_planted_file_too_long(tmp_path):
    _write(tmp_path, "src/pkg/big.py", "x = 1\n" * 251)
    assert any("251 lines" in e for e in size_budget.check(tmp_path))


def test_size_budget_planted_total_too_long(tmp_path):
    for i in range(7):
        _write(tmp_path, f"src/pkg/m{i}.py", "x = 1\n" * 240)
    assert any("total 1680" in e for e in size_budget.check(tmp_path))


def test_map_check_planted_missing_module(tmp_path):
    _write(tmp_path, "src/pkg/a.py", "")
    _write(tmp_path, "src/pkg/b.py", "")
    _write(tmp_path, "MAP.md", "- src/pkg/a.py\n")
    assert map_check.check(tmp_path) == ["src/pkg/b.py not in MAP.md"]


def test_claims_check_planted_missing_path_and_pathless_line(tmp_path):
    _write(tmp_path, "reports/artifacts/ok.txt", "1")
    _write(tmp_path, "reports/r.md", "MEASURED: 3 (`reports/artifacts/ok.txt`)\n"
                                     "MEASURED: 4 (`reports/artifacts/missing.txt`)\n"
                                     "MEASURED: 5 with no artifact\n")
    errors = claims_check.check(tmp_path)
    assert len(errors) == 2 and "missing.txt" in errors[0] and "no artifact" in errors[1]


def test_unit_test_runner_planted_failure(tmp_path):
    _write(tmp_path, "test_planted.py", "def test_planted():\n    assert 1 == 2\n")
    res = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(tmp_path)],
                         capture_output=True, text=True)
    assert res.returncode != 0


def test_offline_guard_blocks_network():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("www.sec.gov", 443), timeout=1)
