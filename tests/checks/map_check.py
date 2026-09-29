"""MAP check: every module under src/ is named (by path) in MAP.md."""

from __future__ import annotations

import sys
from pathlib import Path


def check(root: Path) -> list[str]:
    map_file = root / "MAP.md"
    if not map_file.exists():
        return ["MAP.md missing"]
    text = map_file.read_text()
    modules = sorted(p for p in (root / "src").rglob("*.py") if "__pycache__" not in p.parts)
    if not modules:
        return ["no modules found under src/"]
    return [f"{m.relative_to(root)} not in MAP.md" for m in modules if str(m.relative_to(root)) not in text]


def main(root: Path) -> int:
    errors = check(root)
    for e in errors:
        print("MAP FAIL:", e)
    if not errors:
        print("map check: ok")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()))
