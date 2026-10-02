# edgar13f-mcp

An [MCP](https://modelcontextprotocol.io) server that answers questions about SEC Form 13F
holdings **as they could have been known on a given date**. It comes with an evaluation that
was frozen before the server was written.

## What it does, and why point-in-time matters

Institutional managers with US$100m or more in 13F securities file Form 13F every quarter, up
to 45 days after the quarter ends. Many of them later amend the report. A **restatement**
replaces the whole report. A **new-holdings** amendment adds rows to it. So "what did manager
X hold at 2024-12-31?" has different correct answers on different days: nothing before the
filing date, then the original report, and later the amended one.

A tool that always returns the latest version leaks the future into backtests, research notes
and agent answers. This server takes an `as_of` date with every call and follows two rules
(full text in [`contracts/CONTRACTS.md`](contracts/CONTRACTS.md)):

* **Visibility (§3):** a filing is visible on `as_of` only if its EDGAR filing date is on or
  before `as_of`. Nothing filed later affects the answer: not the rows, the citations, the
  filing list, or which filing counts as "latest".
* **Amendments (§4):** the visible filings for the period are put in order. The base is the
  last original or restatement. Every later new-holdings amendment is added to it. Each row
  cites the filing it came from.

## Install and run

Python 3.11, with the official MCP Python SDK 2.x. The server speaks MCP over stdio only.

One command, straight from GitHub (needs [uv](https://docs.astral.sh/uv/); nothing is published to a
package registry):

```sh
export SEC_USER_AGENT="Your Name your.email@example.com"   # required by SEC fair access
uvx --python 3.11 --from git+https://github.com/Serios16/edgar13f-mcp edgar13f-server
```

Append a tag to pin a release, e.g. `git+https://github.com/Serios16/edgar13f-mcp@V1.1.0` (that tag
is spelled with a capital V; `@v1.0.0` is lower-case). For an MCP client such as Claude Desktop:

```json
{"mcpServers": {"edgar13f": {
  "command": "uvx",
  "args": ["--python", "3.11", "--from", "git+https://github.com/Serios16/edgar13f-mcp", "edgar13f-server"],
  "env": {"SEC_USER_AGENT": "Your Name your.email@example.com"}}}}
```

This command is tested by `tests/tools/install_smoke.sh` (empty uv cache, MCP handshake; output in
`reports/artifacts/install_smoke.txt`). From a clone instead:

```sh
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e .
export SEC_USER_AGENT="Your Name your.email@example.com"   # required by SEC fair access
python -m edgar13f.server                                   # or: edgar13f-server
```

Environment variables:

* `SEC_USER_AGENT`: the User-Agent sent to sec.gov. It is required; without it the server
  does not contact sec.gov.
* `EDGAR13F_CACHE_DIR`: the on-disk cache. The default is `$XDG_CACHE_HOME/edgar13f` (or
  `~/.cache/edgar13f`), then a private per-user temp dir. The server writes nowhere else.
* `EDGAR13F_REDACT`: set to exactly `off` to return the rows that are redacted by default (see
  Limits). Any other value, or none, keeps redaction on.
* `EDGAR13F_AGENT_MODE`: set to exactly `on` to cap unnarrowed holdings and diff answers at the
  50 largest positions (see [Agent use](#agent-use-addendum-a)). Unset, every v1 call answers
  byte for byte as in v1.1.0.
* `EDGAR13F_FIXTURE_DIR`: serve recorded fixtures instead of EDGAR (used by the tests; refused
  together with `EDGAR13F_REDACT=off`).

SEC access follows the fair-access policy. Across processes that share a cache dir, request
starts are spaced at least 0.25 s apart (under 5 per second). 403/429/5xx responses and HTML
error pages trigger exponential backoff. Responses are cached on disk.

## The tools

| Tool | Returns |
|---|---|
| `find_manager(name[, as_of][, limit])` | CIK candidates whose current or former EDGAR name contains `name`, managers with 13F filings first. `entity_name` is EDGAR's current name (not point-in-time); with `as_of`, `has_13f_filings` counts only 13F filings dated on or before it. |
| `list_13f_filings(cik, as_of[, period])` | Every 13F-HR, 13F-HR/A, 13F-NT and 13F-NT/A filed by the manager on or before `as_of` (only those for `period` if given), with period, amendment number and type, report type, manager name and an EDGAR link. |
| `get_holdings_as_of(cik, period, as_of[, cusip][, issuer][, max_positions][, position_type])` | The effective holdings for one quarter as known on `as_of`, row by row as filed (no merging or rescaling). It cites the base filing and every applied amendment. |
| `diff_holdings(cik, period_a, period_b, as_of[, cusip][, issuer][, max_positions])` | Position changes between two quarters, both resolved on the same `as_of`, keyed by (CUSIP, put/call, SH/PRN): added, removed, increased, decreased or unchanged. |

`find_manager`, `period`, `issuer` and `max_positions` come from
[Addendum A](contracts/CONTRACTS_ADDENDUM_A.md.) (additive: a call that uses none of them gets
exactly the v1.1.0 answer).

Every response is a JSON object with the disclaimer *"13F reports long positions only; data
may lag the period end by up to 45 days."* When the server cannot answer, it returns a normal
result with `status: "declined"` and one of six reasons: `unknown_cik`, `not_yet_filed`,
`notice_only`, `invalid_period`, `invalid_argument`, `unsupported_request`.

## Agent use (Addendum A)

The extensions are meant for LLM agents, which usually start from a name and cannot read a
40 MB answer. A typical sequence:

```jsonc
// 1. name -> CIK (managers that have filed Form 13F come first)
{"tool": "find_manager", "arguments": {"name": "berkshire hathaway", "as_of": "2025-08-27"}}
// 2. which filings make up one quarter, as of a date
{"tool": "list_13f_filings", "arguments": {"cik": "1067983", "as_of": "2025-08-27", "period": "2025-03-31"}}
// 3. one issuer only; the answer adds matched_cusips
{"tool": "get_holdings_as_of", "arguments": {"cik": "1067983", "period": "2025-03-31", "as_of": "2025-08-27",
                                              "issuer": "apple"}}
// 4. the 10 largest positions; the answer adds total_positions, truncated and order
{"tool": "get_holdings_as_of", "arguments": {"cik": "1067983", "period": "2025-03-31", "as_of": "2025-08-27",
                                              "max_positions": 10}}
// 5. the 20 largest changes by |value_delta|
{"tool": "diff_holdings", "arguments": {"cik": "1067983", "period_a": "2024-12-31", "period_b": "2025-03-31",
                                         "as_of": "2025-08-27", "max_positions": 20}}
```

* `issuer` (2-100 characters) keeps rows whose issuer name contains it, ignoring case and runs of
  whitespace; it combines with `cusip` as AND.
* `max_positions` (1-200) ranks positions, i.e. (CUSIP, put/call, SH/PRN) groups, by summed value
  (holdings) or by |value_delta| (diff), and returns the top ones with all their rows. A position
  is never split, so a manager that files many rows per position can still return many rows; use
  `issuer` or `cusip` for one security.
* The new parameters only filter or order rows. Citations (`accession_number`,
  `source_accessions`, `filing_date`) and point-in-time behaviour are unchanged, and redaction
  happens before any filter.
* `find_manager` matches every current and former EDGAR name, returns EDGAR's current name, and
  is therefore not point-in-time for names. Its first call on an empty cache reads EDGAR's
  quarterly form indexes since 1993 (about a minute, once per cache directory); later calls take
  milliseconds.

With `EDGAR13F_AGENT_MODE=on`, a `get_holdings_as_of` or `diff_holdings` call that has none of
`cusip`, `issuer` or `max_positions` is answered as if `max_positions` were 50, and the answer
adds `auto_limited: true`. Every other call is unaffected. MCP client config:

```json
{"mcpServers": {"edgar13f": {
  "command": "uvx",
  "args": ["--python", "3.11", "--from", "git+https://github.com/Serios16/edgar13f-mcp", "edgar13f-server"],
  "env": {"SEC_USER_AGENT": "Your Name your.email@example.com", "EDGAR13F_AGENT_MODE": "on"}}}}
```

## Limits

* **Long positions only.** Form 13F has no short positions, so `position_type` other than
  `"long"` is declined.
* **Lag.** Reports are due up to 45 days after quarter end, and amendments can arrive months
  later. An answer is only as current as what was filed by `as_of`.
* **Redaction.** By default, rows for gold ETFs/trusts, US energy-sector ETFs, S&P 500 index
  funds/ETFs, and UCITS copies of these are removed when the information table is parsed,
  because the author keeps a separate study blind to these instruments. They are then never
  returned, cached or logged. Matching uses issuer-name and title patterns plus a CUSIP list,
  and deliberately errs toward removing too much. Some ordinary securities are dropped too. Two
  concrete cases cost graded points: every "SPDR S&P ..." fund (any SPDR fund that names S&P,
  not only S&P 500 ones), and bonds of issuers named like a trust or fund whose class title
  carries a ".500" coupon (e.g. "5.500% NOTES"). An energy company whose class title says
  "UNIT" is another. Ruling D2 forbids narrowing the list to recover such points. A query for a
  removed CUSIP returns `ok` with no rows. `find_manager` also leaves out entities whose names
  match the list (REGISTER N1). To switch redaction off, set `EDGAR13F_REDACT=off` (exactly
  `off`); rows read that way are cached in a separate directory and never served once
  redaction is back on. See `CLAUDE.md` rule 2 and ruling D2 in `REGISTER.md`.
* The server does not cover pre-2013 text-format 13F filings, and it has no prices, charts or
  performance figures.

## How it is evaluated

* **Hidden, frozen grader.** The gold sets, leakage set and grader were frozen in a separate
  private repository before any server code existed. The builder cannot read or write that
  repository. [`contracts/PREREG_COMMITMENT.md`](contracts/PREREG_COMMITMENT.md) holds the
  SHA-256 of that repository's manifest and of the contract files copied here. Everything will
  be published after the final stage so the hash can be checked.
* **Gold sets:** 40 curated items and 700 generated items, stratified by case type (for
  example the day before and the day of a restatement), plus 3,114 leakage cases.
* **Controls in this repository.** They run in CI on every push, offline; the tests refuse
  sockets:
  * a leakage suite with a *mutant* control (visibility check disabled; it must find
    violations) and a *no-op* control;
  * blocklist proofs on synthetic rows, with a planted failure;
  * an exhaustive check of the §4 amendment rules against an independent oracle, killed by
    each planted rule mutation (`tests/unit/test_restatement.py`);
  * size, map and claims checks, each with a planted failure.
* **OS-level isolation.** CI runs the server as a separate unprivileged OS user from a
  read-only copy of the checkout. The job fails if that user creates any file or directory
  outside the expected cache dir, and a planted stray write must be caught
  (`tests/tools/unprivileged_probe.sh`).
* **External cross-check (test time only).** `tests/tools/datasets_crosscheck.py` compares
  answers for randomly sampled (cik, period, as_of) triples against the SEC Form 13F Data
  Sets. The server never reads the data sets.

### Gate results (REPORTED by the evaluator; aggregates only)

Item-level results are withheld by design. Gate 2, the pre-registered decision gate, passed on
commit b208c47, which is tagged **v1.0.0**. Gate 3 passed on commit ca60c5c, which is tagged
**v1.1.0** (spelled `V1.1.0` on GitHub). Both have the same aggregates as gate 1.

| Measure | Gate 1 | Gate 2 (v1.0.0) | Gate 3 (v1.1.0) |
|---|---|---|---|
| Primary gates | all PASS | all PASS | all PASS |
| Generated items | 698 / 700 | 698 / 700 | 698 / 700 |
| Generated misses | 1 `restatement_before`, 1 `restatement_after` | same | same; both are D2 over-matches |
| Citation validity | 669 / 671 | 669 / 671 | 669 / 671 |
| Leakage | 0 violations over 3,114 cases | 0 over 3,114 | 0 over 3,114 |
| Curated items | 34 / 34 | 34 / 34 | 34 / 34 |
| Declines | 6 / 6 | 6 / 6 | 6 / 6 |

Both generated misses come from ruling D2: the blocklist removes rows the grader expected (see
Limits for the two known over-match patterns). D2 forbids narrowing the list to win them back.

**Out of sample.** On filings dated 2025-09 to 2026-08, outside the window the frozen evaluation
covers (as_of up to 2025-08-27), all primary gates PASS: generated 699 / 700, 0 leakage
violations over 3,102 cases, citations 639 / 640, declines 6 / 6. The one miss is a D2
over-match, predicted before grading.

v1.2.0 is tagged only if gate 4, run on the merged stage-4 commit, passes every primary gate
with generated >= 698/700 and 0 leaks (pre-registered in `REGISTER.md`).

### Latency

Cold start (empty cache), `get_holdings_as_of(cik, 2025-03-31, as_of=2025-08-27)` for the five
13F-HRs of that quarter with the most rows after redaction, measured in-process (MEASURED;
`tests/tools/cold_latency.py`, artifacts `reports/artifacts/cold_latency_stage3_*.json`). Each
cell is the worst of two runs (v1.0.0) or three runs (v1.1). For 1776033 a restatement filed the
next day replaces the 34,332-row original, so the answer has 1,599 rows.

| CIK | Rows | v1.0.0 | v1.1 | SEC requests |
|---|---|---|---|---|
| 2012383 | 50,158 | 8.3 s | 4.1 s | 9 -> 6 |
| 319933 | 49,594 | 8.1 s | 4.3 s | 9 -> 5 |
| 1761755 | 44,548 | 16.2 s | 4.2 s | 31 -> 5 |
| 895421 | 44,192 | 44.5 s | 7.6 s | 118 -> 13 |
| 1776033 | 1,599 | 8.1 s | 2.9 s | 23 -> 6 |

v1.1 reads only the cover pages and history pages that can affect the requested quarter.
Warm calls take under 0.6 s. `list_13f_filings` still reads every filing's cover page, so its
first call costs 2-36 s for these managers. Over MCP stdio the server adds about 1 s for a
50k-row answer (~40 MB), but the MCP Python SDK's stdio client (2.2.0) itself needs 6-15 s to
read a message that large.

Stage reports with measured artifacts are in [`reports/`](reports/).

## Tests

```sh
pip install -e ".[test]"
python -m pytest -q tests          # offline; sockets are refused
python tests/checks/size_budget.py . && python tests/checks/map_check.py . && python tests/checks/claims_check.py .
```

`MAP.md` lists the modules and shows where each contract rule is enforced and tested.
`REGISTER.md` records rulings, assumptions and proposals.

## Licence

MIT; see [`LICENSE`](LICENSE). Runtime dependencies use permissive OSI licences only
(MIT/Apache/BSD/PSF/ISC). This project does not use edgartools and contains no code from
AGPL projects. It is not affiliated with the SEC, and nothing it returns is investment advice.
