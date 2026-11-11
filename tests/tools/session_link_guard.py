"""CI guard (CLAUDE.md rule 10): no claude.ai session link and no "Claude-Session:" trailer in the
commit messages between the PR base and head, the PR title or the PR body.

Reads PR_TITLE, PR_BODY, BASE_SHA and HEAD_SHA from the environment (never from shell interpolation).
"""

from __future__ import annotations

import os
import subprocess
import sys

# Built from parts so this file is not itself a hit for a text search of the repository.
FORBIDDEN = ("claude.ai/code/" + "session_", "Claude-" + "Session:")


def hits(text: str) -> list[str]:
    low = text.lower()
    return [f for f in FORBIDDEN if f.lower() in low]


def commit_messages(base: str, head: str) -> list[tuple[str, str]]:
    out = subprocess.run(["git", "log", "--format=%H%x00%B%x01", f"{base}..{head}"],
                         capture_output=True, text=True, check=True).stdout
    pairs = []
    for rec in out.split("\x01"):
        if rec.strip():
            sha, _, body = rec.strip().partition("\x00")
            pairs.append((sha, body))
    return pairs


def check(title: str, body: str, base: str, head: str) -> list[str]:
    errors = [f"PR title contains {h!r}" for h in hits(title)]
    errors += [f"PR body contains {h!r}" for h in hits(body)]
    for sha, msg in commit_messages(base, head):
        errors += [f"commit {sha[:10]} message contains {h!r}" for h in hits(msg)]
    return errors


def main() -> int:
    errors = check(os.environ.get("PR_TITLE", ""), os.environ.get("PR_BODY") or "",
                   os.environ["BASE_SHA"], os.environ["HEAD_SHA"])
    for e in errors:
        print("SESSION LINK FAIL:", e)
    if not errors:
        print("session link guard: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
