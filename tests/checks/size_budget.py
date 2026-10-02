"""Size budget: <= 1,500 lines under src/, <= 250 lines per file.

Build metadata that `pip install -e` writes into src/ (`*.egg-info/`, untracked; its PKG-INFO
embeds README.md) is not source and is not counted (stage 4, REGISTER A30)."""

from __future__ import annotations

import sys
from pathlib import Path

TOTAL_MAX, FILE_MAX = 1500, 250


def check(root: Path) -> list[str]:
    errors, total = [], 0
    files = sorted(p for p in (root / "src").rglob("*") if p.is_file() and "__pycache__" not in p.parts
                   and not any(part.endswith(".egg-info") for part in p.parts))
    for path in files:
        n = len(path.read_text(errors="replace").splitlines())
        total += n
        if n > FILE_MAX:
            errors.append(f"{path.relative_to(root)}: {n} lines > {FILE_MAX}")
    if total > TOTAL_MAX:
        errors.append(f"src/ total {total} lines > {TOTAL_MAX}")
    return errors


def main(root: Path) -> int:
    errors = check(root)
    for e in errors:
        print("SIZE BUDGET FAIL:", e)
    if not errors:
        print("size budget: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))
