# Stage 4 report: agent-use extensions

Labels: each claim is tagged measured, reported, reasoned or assumed (upper-case tag on the line);
untagged = assumed. Artifacts are in `reports/artifacts/`. Live results come from sec.gov with
`SEC_USER_AGENT` set, the <= 5 req/s limiter and on-disk caches outside the repo; live jobs ran one
at a time. The acceptance criteria were fixed by the brief before any work. Item-level gate results
were not looked for.

REPORTED (evaluator, aggregates only): gate 3 PASS on ca60c5c, tagged v1.1.0: generated 698/700, 0 leaks,
identical to gates 1-2; both misses are ruling D2 over-matches. Out of sample (filings 2025-09 to
2026-08): 699/700, 0 leaks over 3,102 cases, citations 639/640, declines 6/6, all primary gates PASS;
the one miss is a D2 over-match, predicted before grading.

`src/` against v1.1.0: 9 files changed, 2 of them new (`narrow.py`, `managers.py`), +430/-44 lines; 1,429 lines in total, none over 250.
MEASURED: size budget, MAP and claims checks pass, and the full suite passes offline (408 passed, 1 skipped: the root-only test); see `reports/artifacts/pytest_stage4.txt`.

## a. Addendum A (A1-A6)

No part needed a contract change. Readings of points the addendum leaves open are logged as
ASSUMED A22-A28 in `REGISTER.md` (trigger: stage gate). One blocklist question is open as
DECISION NEEDED N1 (below).

| Item | Where | What it does |
|---|---|---|
| A1 `issuer` | `validate.fold`, `narrow.keep` | Case-insensitive substring of `name_of_issuer`, whitespace runs collapsed on both sides; AND with `cusip`; `matched_cusips` (distinct, as filed, sorted; before any cut). |
| A2 `max_positions` | `narrow.holdings`, `narrow.changes` | Holdings: (cusip, put_call, sh_prn) groups by summed value desc, then cusip, put_call (null first), sh_prn; whole groups. Diff: changes by abs(value_delta), same tie-breaks. Adds `total_positions`, `truncated`, `order`. |
| A3 `period` (list) | `tools.list_13f_filings` | The visible list filtered by period; reads only what can bear on that period (A17). |
| A4 `find_manager` | `managers.py` | Names from EDGAR's CIK lookup file (current and former), `has_13f_filings` from EDGAR's quarterly form indexes through `rules.visible`, `entity_name` from the submissions JSON; 13F filers first, then current name. |
| A5 agent mode | `narrow.agent_mode` | `EDGAR13F_AGENT_MODE` exactly `on`: unnarrowed holdings/diff calls get `max_positions=50` and `auto_limited: true`. |
| A6 descriptions | `schemas.py` | Point models to `find_manager`, to `issuer`/`cusip`/`max_positions`, and say `as_of` = publicly filed by that date. |

Evidence:

- A0, unchanged v1 test: MEASURED: 3,689 of 3,689 golden calls byte-identical to v1.0.0 (= v1.1.0) with `EDGAR13F_AGENT_MODE` unset (`tests/unit/test_golden.py`, unchanged); part of `reports/artifacts/pytest_stage4.txt`.
- MEASURED: every holdings/diff call of the golden grid, rerun with `max_positions=1`, `issuer="INC"` and `issuer="corp"` + `max_positions=200`, keeps status, reason and every citation field (more than 2,000 calls), and with agent mode on every call it does not apply to is byte-identical to v1.0.0 (`tests/unit/test_addendum.py`); part of `reports/artifacts/pytest_stage4.txt`.
- Tests per parameter and tool: `tests/unit/test_addendum.py` (A1, A2, A3, A5, A6: exact orders on an invented manager that pins every tie-break, boundaries and bad types for each parameter, precedence), `tests/unit/test_find_manager.py` (A4: ordering, renamed entities, `as_of` boundaries, limit, declines, laziness; `EdgarDirectory` on a fake SEC client: Range prefixes, per-quarter cache and freshness, missing indexes, concurrent first calls), `tests/unit/test_server_stdio.py` (the four tools over MCP stdio).
- Leakage suite: the 981 cases now also call, where they apply, `list_13f_filings(period)`, `get_holdings_as_of` with `issuer`+`max_positions`, with `max_positions=1` and in agent mode, `diff_holdings` with `issuer`+`max_positions`, and `find_manager(name, as_of)` (oracle: every candidate's `has_13f_filings` == its earliest fixture 13F <= `as_of`). MEASURED: 0 violations; the mutant control (as-of filter off) finds 12,314, in every one of the 9 categories (`find_manager`: 11); the no-op control 0; see `reports/artifacts/leakage_stage4.json`.
- Blocklist: redaction precedes every new filter (synthetic rows: `issuer`, `max_positions` and agent mode never see a blocked row; with the switch off on the same synthetic rows they would). MEASURED: 81 tests in `tests/invariants/test_blocklist.py` pass, incl. planted failures; part of `reports/artifacts/pytest_stage4.txt`.

DECISION NEEDED N1 (blocklist): hard rule 2 covers holdings rows, but `find_manager` returns
entity names, some of which name blocked instruments (e.g. a gold trust registrant). This branch
takes the conservative reading: while redaction is on, a candidate is left out if any of its
current or former names matches the blocklist name patterns. Nothing is narrowed. The owner may
keep or drop it (REGISTER N1, A27).

## b. P7: truncated downloads

`SecClient` now retries `http.client.HTTPException` (incl. `IncompleteRead`) with the same
exponential backoff as network errors and logs each as `neterr:<name>` in `requests.log` (A29).
Tests use a fake opener that cuts bodies mid-transfer, plus one through the real `_urlopen` path.
MEASURED: the 5 P7 tests fail 4 of 5 on the v1.1.0 client (ca60c5c) and pass on this branch; see `reports/artifacts/p7_before_after.txt`.

## c. Measurements

Method: `python -m tests.tools.agent_latency --ciks 2012383,319933,1761755,895421,1776033`, two runs,
each part in a fresh empty cache dir, in-process `tools.call` on `EdgarSource` (A15). `find_manager`
query = the filer's current EDGAR name. Cells: worst run (each run).

| CIK | `find_manager` cold (s) | requests | warm (s) | new process (s) | `list_13f_filings(period)` cold (s) | requests | warm (s) | full list cold, stage 3 (s) |
|---|---|---|---|---|---|---|---|---|
| 2012383 | 67.28 (66.48, 67.28) | 139/139 | 0.03 (0.03, 0.03) | 3.21 (3.21, 1.74) | 1.24 (1.24, 1.05) | 4/4 | 0.00 (0.00, 0.00) | 2.0 |
| 319933 | 69.29 (66.59, 69.29) | 138/138 | 0.02 (0.02, 0.02) | 2.13 (2.13, 1.72) | 0.71 (0.71, 0.69) | 3/3 | 0.00 (0.00, 0.00) | 2.4 |
| 1761755 | 66.41 (66.41, 63.78) | 138/138 | 0.02 (0.02, 0.02) | 2.11 (2.11, 1.81) | 0.80 (0.80, 0.71) | 3/3 | 0.00 (0.00, 0.00) | 9.2 |
| 895421 | 75.24 (75.24, 63.51) | 147/147 | 0.05 (0.05, 0.05) | 2.58 (2.58, 1.81) | 3.73 (3.73, 3.43) | 11/11 | 0.03 (0.03, 0.03) | 35.5 |
| 1776033 | 78.76 (78.76, 63.05) | 138/138 | 0.02 (0.02, 0.02) | 2.38 (2.38, 1.88) | 2.14 (2.14, 1.21) | 4/4 | 0.00 (0.00, 0.00) | 5.6 |

MEASURED: the table above; runs 1 and 2 in `reports/artifacts/agent_latency_run1.json` and `reports/artifacts/agent_latency_run2.json`; the stage-3 column is the v1.1 worst of three from `reports/artifacts/cold_latency_stage3_after_run1.json` (runs 2-3 likewise).

- MEASURED: a cold `find_manager` takes 63-79 s: it reads the CIK lookup file (40 MB), one 1 MiB prefix of each of the 136 quarterly form indexes and 1-10 submissions files (138-147 requests). Each index request takes 0.41-0.48 s (median per build), mostly round-trip time: the 1993 QTR2-QTR4 indexes (under 1 KB each) take 0.23-0.50 s (the QTR1 gap also includes parsing the lookup file); see `reports/artifacts/find_manager_request_timing.json` (from the ten builds' request logs) and `reports/artifacts/agent_latency_run1.json`.
- MEASURED: warm calls 0.02-0.05 s; a new process on the same cache (index and names on disk) 1.7-3.2 s, with no request; the same answer every time, in both runs; see `reports/artifacts/agent_latency_run2.json`.
- MEASURED: every filer is found with `has_13f_filings: true`, with and without `as_of` (2025-08-27), in both runs; rank 1 for three, rank 2 for BlackRock (behind "BlackRock Finance, Inc.", the pre-2024 BlackRock CIK that matches through its former name) and Morgan Stanley (behind a Mitsubishi UFJ Morgan Stanley entity); see `reports/artifacts/agent_latency_run1.json`.
- MEASURED: `list_13f_filings(period)` equals the full list filtered by period for all five filers in both runs, cold in 0.7-3.7 s with 3-11 requests where the full list took 2.0-35.5 s cold in stage 3; see `reports/artifacts/agent_latency_run2.json`.

Response size, `get_holdings_as_of(cik, 2025-03-31, as_of=2025-08-27)` and `diff_holdings(2024-12-31 ->
2025-03-31)`, without and with `max_positions=50` (first text block; the JSON-RPC message with
`structuredContent` is about 2.1 times larger), and the warm call through the MCP Python SDK 2.2.0
stdio client:

| CIK | holdings rows | text | with `max_positions=50` | rows kept | positions | SDK stdio warm (s) | with 50 (s) | diff changes | diff text | with 50 | SDK (s) | with 50 (s) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2012383 | 50,158 | 19.28 MB | 0.44 MB | 1,137 | 50 of 5,355 | 13.62 (11.93, 13.62) | 0.27 (0.20, 0.27) | 5,586 | 1.42 MB | 13.9 KB | 0.51 (0.51, 0.51) | 0.38 (0.38, 0.35) |
| 319933 | 49,594 | 18.88 MB | 6.74 MB | 17,741 | 50 of 1,671 | 11.02 (7.69, 11.02) | 1.28 (1.28, 1.26) | 1,756 | 0.42 MB | 12.8 KB | 0.54 (0.54, 0.34) | 0.32 (0.32, 0.24) |
| 1761755 | 44,548 | 16.72 MB | 1.01 MB | 2,677 | 50 of 1,645 | 6.95 (6.95, 5.95) | 0.25 (0.25, 0.25) | 1,759 | 0.43 MB | 13.0 KB | 0.33 (0.32, 0.33) | 0.26 (0.25, 0.26) |
| 895421 | 44,192 | 16.91 MB | 0.36 MB | 951 | 50 of 7,903 | 7.14 (5.93, 7.14) | 0.24 (0.20, 0.24) | 8,284 | 2.07 MB | 13.7 KB | 0.61 (0.55, 0.61) | 0.39 (0.35, 0.39) |
| 1776033 | 1,599 | 0.62 MB | 25.6 KB | 64 | 50 of 1,555 | 0.06 (0.06, 0.06) | 0.01 (0.01, 0.01) | 1,626 | 0.38 MB | 12.8 KB | 0.04 (0.04, 0.04) | 0.03 (0.02, 0.03) |

MEASURED: sizes identical in both runs; SDK times worst (each run); see `reports/artifacts/agent_latency_run1.json` and `reports/artifacts/agent_latency_run2.json`.

- MEASURED: `max_positions=50` cuts the holdings text 16-46x for four filers and the SDK client's read from 5.9-13.6 s to 0.20-0.27 s for the three large ones; for 319933 only 2.8x (17,741 rows remain, 1.3 s), because A2 never splits a position and that filer reports each position in many rows; see `reports/artifacts/agent_latency_run2.json`.
- MEASURED: diff answers drop to 12.8-13.9 KB (50 changes) from 0.38-2.07 MB (30-151x); see `reports/artifacts/agent_latency_run2.json`.

`has_13f_filings` against `list_13f_filings` (live, seeded): 150 random CIKs from the 13F index at
the day before their first 13F, the day of it and a random later date, plus 150 random CIKs from
EDGAR's lookup file that are not in the index.
MEASURED: 600 of 600 agree (Wilson 95% [0.994, 1.000]): 150/150 day-before (`unknown_cik`), 150/150 day-of (ok), 150/150 random, 150/150 not in index; 0 non-200 responses; see `reports/artifacts/has13f_crosscheck.json`.

Form-index premises (A26), whole files, 1993 QTR1 to 2026 QTR4:
MEASURED: 136 of 136 quarterly indexes sorted by form type (0 pairs out of order), ISO dates, numeric CIK tokens; the 13F block ends within the first 576 KiB compressed in every quarter; 13F-HR lines from 1993 QTR1; 20,289 CIKs with any 13F; see `reports/artifacts/fullindex_verify.json`.

SEC access in this stage:
MEASURED: 2,465 requests in the 34 request logs of this stage (1,984 www.sec.gov, 481 data.sec.gov; 1,636 form-index, 481 submissions, 336 other archive files, 12 CIK lookup files), all HTTP 200 or 206 (no 403/429), at most 5 completions logged in any 1-second window; from `python tests/tools/request_stats.py <logs>`; see `reports/artifacts/sec_requests_stage4.json`.
- Not in the logs: 17 requests made with curl (same User-Agent, one at a time, >= 0.4 s apart) while
  choosing the data source: 15 HEAD requests for file sizes, one company-search query (Atom output
  is broken: names print as `ARRAY(0x...)`) and one HEAD of the 1.57 GB bulk submissions zip.
- REASONED: as in stages 2-3, the log records completion times while the limiter spaces request
  starts >= 0.25 s apart; live jobs ran one at a time. No mirror or other proxy was used besides
  the environment's egress proxy. A cold `find_manager` downloads 126 MiB of index prefixes
  plus the 40 MB lookup file; whole indexes would be 477 MB (`reports/artifacts/find_manager_request_timing.json`).

## d. Upstream issue draft (F6)

`reports/upstream/mcp_sdk_stdio_issue.md`, not posted: a self-contained reproduction (plain-Python
child, synthetic N-MB line, no SEC data), numbers on mcp 2.2.0 (the latest 2.x on PyPI today), and
a linear fix (join pending chunks once a newline arrives).
MEASURED: one 40 MB line takes 8.9 s through `stdio_client`, 9.4 s through its reader loop copied, 0.37 s with the fix, 0.27 s with `readline()` (median of 3); 20 -> 40 MB multiplies the SDK time by 5.7; see `reports/artifacts/sdk_stdio_repro.json`.

## e. README

Gate 3 and out-of-sample results (REPORTED), the two over-match patterns and D2, the tag spelling,
the four tools, an "Agent use" section with a call sequence and an MCP client config with
`EDGAR13F_AGENT_MODE=on`, and the stage-4 latency and size numbers. `tests/tools/install_smoke.sh` now
accepts the four-tool list.
MEASURED: SMOKE OK for this branch (server 1.2.0, four tools) and for tag V1.1.0 (server 1.1.0, three tools), each in 6-7 s from an empty uv cache with uv 0.8.17 and `SEC_USER_AGENT` unset; see `reports/artifacts/install_smoke_stage4.txt`.

## f. REGISTER and version

"Gate 3 PASS -> v1.1.0" with the out-of-sample result, the known over-matches and the v1.2 gate;
DECISION NEEDED N1; ASSUMED A22-A31; P7 done; P8 updated; proposals P10-P12. `pyproject.toml` and
`__version__` are 1.2.0.

## Findings

| # | Finding | Cause | Action |
|---|---|---|---|
| F8 | First `find_manager` on an empty cache takes 63-79 s (136 index requests); later calls are fast. An MCP client with a short tool timeout may give up on the first call. REASONED: the server finishes the build in its worker thread (and a concurrent call waits on the same build), so a retry is fast. | Exactness for broad queries needs every CIK's 13F history; request latency through the limiter (P4). | Measured; proposals P4/P11. |
| F9 | `max_positions` bounds positions, not rows: 50 positions of 319933 are 17,741 rows (6.7 MB). | A2 never splits a group; some filers report one position in hundreds of rows. | README says to use `issuer`/`cusip` for one security. No change (contract). |
| F10 | Two threads writing the same cache file shared one temporary name (pid only); one rename failed. Found by the new concurrency test. | `_write_json` / HTTP cache temp names (v1). | Fixed: temp names per process and thread; tested. |
| F11 | The gate-3 tag is `V1.1.0` (capital V); `@v1.1.0` does not resolve. | Tag spelling. | README uses `@V1.1.0`; proposal P10. |
| F12 | The addendum file is `contracts/CONTRACTS_ADDENDUM_A.md.` (trailing dot). | File name. | Not renamed (read-only); P12. |

## v1.2 gate (pre-registered, not yet run)

Tag v1.2.0 only if gate 4, run on the merged commit, passes every primary gate with generated
>= 698/700 and 0 leaks. The PR is not merged by the builder.

REASONED, why gate 4 should match gate 3: a call that uses none of the new parameters or tools runs
the v1.1.0 code path (A0, golden test above); the shared changes are the HTTP retry (more robust,
same answers), the thread-safe temp names and the version string.
