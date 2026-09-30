"""Summarise SEC requests from one or more requests.log files (count, max per 1 s window)."""

from __future__ import annotations

import bisect
import json
import sys
from collections import Counter


def main(paths: list[str]) -> None:
    entries = [json.loads(line) for p in paths for line in open(p) if line.strip()]
    ts = sorted(e["t"] for e in entries)
    worst = max((bisect.bisect_left(ts, t + 1.0) - i for i, t in enumerate(ts)), default=0)
    hosts = Counter(e["url"].split("/")[2] for e in entries)
    status = Counter(str(e["status"]) for e in entries)
    print(json.dumps({"requests": len(entries), "max_requests_in_any_1s_window": worst,
                      "by_host": hosts, "by_status": status, "logs": len(paths)}, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
