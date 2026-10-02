"""Write case/violation counts for the leakage suite and its two controls (offline)."""

from __future__ import annotations

import json

from edgar13f import rules
from collections import Counter

from tests.invariants.leakage import run_suite


def main() -> None:
    out = {}
    stats: dict = {}
    n, v = run_suite(stats=stats)
    out["real"] = {"cases": n, "tool_calls": stats, "violations": len(v)}
    original = rules.visible
    rules.visible = lambda f, a: True
    n, v = run_suite()
    out["mutant_as_of_filter_disabled"] = {"cases": n, "violations": len(v),
                                           "by_category": dict(Counter(x.split()[1].rstrip(":") for x in v))}
    rules.visible = lambda f, a: original(f, a)
    n, v = run_suite()
    out["noop_wrapper"] = {"cases": n, "violations": len(v)}
    rules.visible = original
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
