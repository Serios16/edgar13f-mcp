"""Print the license of every distribution in the runtime closure of edgar13f (not run in CI)."""

from __future__ import annotations

import importlib.metadata as md

from packaging.requirements import Requirement

ALLOWED = ("MIT", "APACHE", "BSD")


def closure(name: str, seen: dict) -> None:
    key = name.lower().replace("_", "-")
    if key in seen:
        return
    dist = md.distribution(name)
    seen[key] = dist
    for spec in dist.requires or []:
        req = Requirement(spec)
        if req.marker and not req.marker.evaluate({"extra": ""}):
            continue
        closure(req.name, seen)


def main() -> None:
    seen: dict = {}
    closure("edgar13f", seen)
    for key, dist in sorted(seen.items()):
        lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        lic = lic.splitlines()[0][:40] if lic else "?"
        ok = "ok" if any(a in lic.upper() for a in ALLOWED) else "NOT-ALLOWED"
        print(f"{key:28s} {dist.version:12s} {lic:20s} {ok}")


if __name__ == "__main__":
    main()
