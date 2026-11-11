"""Planted tests for tests/tools/session_link_guard.py: it must catch a sample body, title and commit."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.tools import session_link_guard as g

LINK = "https://claude.ai/code/" + "session_0123456789abcdef"
TRAILER = "Claude-" + "Session: " + LINK


def _repo(tmp: Path, message: str) -> tuple[str, str]:
    def git(*a: str) -> str:
        return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *a], cwd=tmp,
                              capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q")
    (tmp / "f").write_text("1")
    git("add", "f")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD")
    (tmp / "f").write_text("2")
    git("commit", "-qam", message)
    return base, git("rev-parse", "HEAD")


def test_clean_pr_passes(tmp_path, monkeypatch):
    base, head = _repo(tmp_path, "ordinary change\n\nCo-Authored-By: Someone <a@example.com>")
    monkeypatch.chdir(tmp_path)
    assert g.check("A title", "A body.\n", base, head) == []


def test_planted_body_is_caught(tmp_path, monkeypatch):
    base, head = _repo(tmp_path, "ordinary change")
    monkeypatch.chdir(tmp_path)
    errors = g.check("A title", f"Summary.\n\n{LINK}\n", base, head)
    assert errors == ["PR body contains 'claude.ai/code/session_'"]


def test_planted_title_and_case_are_caught(tmp_path, monkeypatch):
    base, head = _repo(tmp_path, "ordinary change")
    monkeypatch.chdir(tmp_path)
    assert g.check(f"x {LINK.upper()}", "", base, head)
    assert g.check("x", TRAILER.lower(), base, head)


def test_planted_commit_message_is_caught(tmp_path, monkeypatch):
    base, head = _repo(tmp_path, f"change\n\n{TRAILER}")
    monkeypatch.chdir(tmp_path)
    errors = g.check("A title", "", base, head)
    assert len(errors) == 2 and all(e.startswith("commit ") for e in errors)
