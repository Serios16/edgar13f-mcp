"""Print the license of every distribution in the runtime closure of edgar13f (not run in CI)."""

from __future__ import annotations

import importlib.metadata as md

from packaging.requirements import Requirement

ALLOWED = ("MIT", "APACHE", "BSD", "PSF", "ISC")  # CLAUDE.md rule 4 (ruling D3, 2026-09-29)


def closure(name: str, seen: dict, visited: set, extras: frozenset = frozenset()) -> None:
    """Add `name` and its runtime dependencies; follow the extras a dependent requests (`pyjwt[crypto]`)."""
    key = name.lower().replace("_", "-")
    if (key, extras) in visited:
        return
    visited.add((key, extras))
    dist = md.distribution(name)
    seen[key] = dist
    for spec in dist.requires or []:
        req = Requirement(spec)
        if req.marker and not any(req.marker.evaluate({"extra": e}) for e in ("", *extras)):
            continue
        closure(req.name, seen, visited, frozenset(req.extras))


def main() -> None:
    seen: dict = {}
    closure("edgar13f-mcp", seen, set())
    for key, dist in sorted(seen.items()):
        lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        lic = lic.splitlines()[0][:40] if lic else "?"
        ok = "ok" if any(a in lic.upper() for a in ALLOWED) else "NOT-ALLOWED"
        print(f"{key:28s} {dist.version:12s} {lic:20s} {ok}")


if __name__ == "__main__":
    main()
