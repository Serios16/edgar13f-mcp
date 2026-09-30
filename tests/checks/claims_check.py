"""Claims check: every MEASURED line in reports/ names >= 1 path, and every
backticked path on it exists in the commit (git-tracked; filesystem if no git)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_TICK = re.compile(r"`([^`\s]+)`")


def _tracked(root: Path) -> set[str] | None:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return set(out.stdout.splitlines())


def _is_path(token: str) -> bool:
    return "/" in token and not token.startswith(("http://", "https://"))


def check(root: Path) -> list[str]:
    tracked = _tracked(root)
    errors = []
    for report in sorted((root / "reports").rglob("*.md")):
        for no, line in enumerate(report.read_text().splitlines(), 1):
            if not re.search(r"\bMEASURED\b", line):
                continue
            where = f"{report.relative_to(root)}:{no}"
            paths = [t.rstrip("/") for t in _TICK.findall(line) if _is_path(t)]
            if not paths:
                errors.append(f"{where}: MEASURED line names no artifact path")
            for p in paths:
                ok = (p in tracked or any(t.startswith(p + "/") for t in tracked)) if tracked is not None \
                    else (root / p).exists()
                if not ok:
                    errors.append(f"{where}: path `{p}` not in commit")
    return errors


def main(root: Path) -> int:
    errors = check(root)
    for e in errors:
        print("CLAIMS FAIL:", e)
    if not errors:
        print("claims check: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))
