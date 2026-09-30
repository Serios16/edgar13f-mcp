# edgar13f-mcp
MCP server for SEC 13F holdings with point-in-time correctness and a published eval

Implements the three tools in `contracts/CONTRACTS.md` (`list_13f_filings`,
`get_holdings_as_of`, `diff_holdings`) over MCP stdio, using the official MCP
Python SDK 2.x.

## Install and run

```sh
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e .
export SEC_USER_AGENT="Your Name your.email@example.com"   # required by SEC fair access
python -m edgar13f.server                                   # speaks MCP on stdin/stdout
```

Environment:

* `SEC_USER_AGENT` – User-Agent sent to sec.gov (required for live data).
* `EDGAR13F_CACHE_DIR` – cache directory. Default `$XDG_CACHE_HOME/edgar13f`
  (or `~/.cache/edgar13f`), falling back to a per-user temp dir. The server
  writes nowhere else.
* `EDGAR13F_FIXTURE_DIR` – serve recorded fixtures instead of EDGAR (tests).

Requests to sec.gov are limited to under 5 per second (shared by processes using
the same cache dir), retried with exponential backoff on 403/429/5xx and HTML
error pages, and cached on disk.

Holdings rows for gold ETFs/trusts, US energy-sector ETFs, S&P 500 index
funds/ETFs and UCITS copies are removed at parse time and never returned.

Every response carries the disclaimer: *13F reports long positions only; data
may lag the period end by up to 45 days.*

## Tests

```sh
pip install -e ".[test]"
python -m pytest -q tests          # offline; sockets are refused
python tests/checks/size_budget.py . && python tests/checks/map_check.py . && python tests/checks/claims_check.py .
```

See `MAP.md` for the module map and where each contract rule is enforced and
tested, `REGISTER.md` for decisions and assumptions, and `reports/` for stage
reports.
