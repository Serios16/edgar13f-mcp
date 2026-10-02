# Stage 3 report: release

Labels: each claim is tagged measured, reported, reasoned or assumed (upper-case tag on the line);
untagged = assumed. Artifacts are in `reports/artifacts/`. Live results come from sec.gov with
`SEC_USER_AGENT` set, the <= 5 req/s limiter and on-disk caches outside the repo. The acceptance
criteria were fixed by the brief before any work. Item-level gate results were not looked for.

`src/` changed in 6 files (+107/-53 lines against v1.0.0; 1,043 lines in total; no file over 250).
MEASURED: `python tests/checks/size_budget.py .` passes; see `reports/artifacts/size_budget.txt`.
MEASURED: full suite 269 passed, 1 skipped (root-only skip), offline, from `python -m pytest -q tests`; see `reports/artifacts/pytest_stage3.txt`.

## a. Redaction switch (`EDGAR13F_REDACT`)

- `blocklist.redacting()` is true unless the variable is exactly `off`. `EdgarSource` reads it once
  and passes it to `parse.parse_infotable`; the parser still redacts by default. Rows parsed with
  it off are cached in `rows-unredacted/`, so they are never served with redaction on. The server
  exits if `off` is combined with `EDGAR13F_FIXTURE_DIR`. The live test tools refuse to run with
  it off. The blocklist itself is unchanged (D2). See REGISTER A18.
- Byte-identity with the variable unset: `tests/tools/fixture_golden.py` builds a grid of 3,689
  calls from the fixture files (all 24 recorded managers and the synthetic one: every filing
  date and the day before for `list_13f_filings`, every period with rows at each relevant date,
  CUSIP filters, consecutive-period diffs, notice periods and malformed calls). The v1.0.0 source
  wrote the SHA-256 of each response (`isError` + first text block) to
  `tests/golden/v1_0_fixture_responses.json`. `tests/unit/test_golden.py` recomputes them.
  MEASURED: 3,689 of 3,689 identical, with a planted one-character change detected; part of `reports/artifacts/pytest_stage3.txt`.
- Tests of `off` (synthetic rows only, in the switch section of `tests/invariants/test_blocklist.py`,
  which the existing CI "Blocklist tests" step runs): 13 non-`off` values keep redaction on; `off`
  keeps every synthetic row and writes only `rows-unredacted/`; a cache written with `off` is not
  read with redaction on; the parser default still redacts; a switch that does nothing is caught
  (planted failure); the server refuses `off` with a fixture dir; and no workflow, test or tool
  sets the variable (pattern scan, with 5 planted lines detected). The rows are the invented ones
  from stage 1 (zero values, made-up CUSIPs), served by a fake client.
  MEASURED: 62 of 62 tests in that file pass; part of `reports/artifacts/pytest_stage3.txt`.
- REASONED: the server was never run with `off` against live SEC data or recorded fixtures, in
  this session or in CI: no live job set it, `tests/conftest.py` unsets it for every test, and the
  scan above fails if a workflow, test or tool sets it.
- `CLAUDE.md` rule 2 now describes the switch; the default (ON) and the never-run-off rule are as
  the brief states them.

## b. Cold-start latency

Changes (no contract or CI change):

1. Period-aware fetching (REGISTER A17, closes P5 for these tools). For `get_holdings_as_of` and
   `diff_holdings`, `EdgarSource.filings` gets the requested periods. It reads cover pages only
   for filings dated on or after the earliest period, or whose index period is blank or
   requested. It reads older submission pages only if they end on or after that period, or
   while no visible 13F has been found (so `unknown_cik` is unchanged). `list_13f_filings` still
   reads everything.
2. Row parser: one pass over each row's children instead of one scan per field, and the
   blocklist result memoised per table (`is_blocked` is a pure function of name, title and
   CUSIP; 44-50k-row tables have 1.6-7.9k distinct keys). Output equals the v1.0.0 parser, which
   is kept verbatim as a test oracle in `tests/unit/test_parse.py` (edge cases: duplicate
   children, missing and empty fields, CDATA, other namespaces, nested tables, with and without
   redaction).

Method (A15, A20): `python -m tests.tools.cold_latency --ciks 2012383,319933,1761755,895421,1776033 --stdio`
on the five stage-2 filers, `get_holdings_as_of(cik, 2025-03-31, as_of=2025-08-27)` in-process on an
empty cache dir, then warm; `list_13f_filings` cold in a second empty dir; and the same holdings call
end to end over MCP stdio in a third (server subprocess, client reading each response line with
`readline()`). "Before" is the v1.0.0 source (run 1: the checkout at b208c47 before any change;
run 2: the v1.0.0 tree on `PYTHONPATH`); "after" is this branch, three runs. Cells: worst run
(each run).

| CIK | Rows | `get_holdings_as_of` cold, v1.0.0 (s) | cold, v1.1 (s) | Requests | stdio cold, v1.0.0 | stdio cold, v1.1 | `list_13f_filings` cold, v1.0.0 | v1.1 |
|---|---|---|---|---|---|---|---|---|
| 2012383 | 50,158 | 8.3 (8.3, 8.0) | **4.1** (4.1, 3.9, 4.0) | 9 -> 6 | 8.9 | 5.4 (4.9, 5.0, 5.4) | 2.6 (2.6, 1.8) | 2.0 (1.9, 1.9, 2.0) |
| 319933 | 49,594 | 8.1 (7.6, 8.1) | **4.3** (4.3, 4.0, 4.0) | 9 -> 5 | 8.3 | 5.2 (4.3, 4.7, 5.2) | 2.0 (1.7, 2.0) | 2.4 (1.8, 2.4, 1.8) |
| 1761755 | 44,548 | 16.2 (16.2, 13.2) | **4.2** (4.2, 3.8, 3.7) | 31 -> 5 | 14.4 | 4.9 (4.9, 4.3, 4.0) | 7.7 (7.6, 7.7) | 9.2 (8.6, 9.2, 7.8) |
| 895421 | 44,192 | 44.5 (44.5, 41.4) | **7.6** (6.1, 7.2, 7.6) | 118 -> 13 | 40.0 | 7.7 (7.6, 7.7, 7.7) | 34.1 (32.6, 34.1) | 35.5 (33.5, 33.5, 35.5) |
| 1776033 | 1,599 | 8.1 (8.1, 7.0) | **2.9** (2.2, 2.9, 2.1) | 23 -> 6 | 6.5 | 1.9 (1.8, 1.8, 1.9) | 5.8 (5.6, 5.8) | 5.6 (5.5, 5.5, 5.6) |

- MEASURED: target met; cold `get_holdings_as_of` <= 7.6 s for each filer in every after-run (v1.0.0: 7.0-44.5 s); see `reports/artifacts/cold_latency_stage3_after_run1.json`, `reports/artifacts/cold_latency_stage3_after_run2.json`, `reports/artifacts/cold_latency_stage3_after_run3.json`.
- MEASURED: before, two runs of the v1.0.0 source; see `reports/artifacts/cold_latency_stage3_before.json` and `reports/artifacts/cold_latency_stage3_before_run2.json` (run 2 adds the stdio columns).
- MEASURED: every run returned the same answer per filer (status ok, same `source_accessions`, same row count) with 0 non-200 responses; warm calls 0.00-0.52 s; see `reports/artifacts/cold_latency_stage3_after_run1.json` (runs 2-3 and before likewise).
- MEASURED: `list_13f_filings` (reported only) is unchanged by design: 1.8-35.5 s cold, 7-116 requests, as before; see `reports/artifacts/cold_latency_stage3_after_run1.json` (runs 2-3 and before likewise).
- MEASURED: end to end over stdio with a line-reading client, cold <= 7.7 s after (v1.0.0: up to 40.0 s); the server writes a 44-50k-row answer (~40 MB) in about 1 s; see the `stdio_*` fields of `reports/artifacts/cold_latency_stage3_after_run1.json` (runs 2-3 likewise) and `reports/artifacts/cold_latency_stage3_before_run2.json`.
- MEASURED: the same warm call through the MCP Python SDK 2.2.0 stdio client takes 6.2-14.5 s for the four 44-50k-row answers (0.1 s for 1,599 rows), in every run; see `stdio_warm_sdk_client_s` in `reports/artifacts/cold_latency_stage3_after_run1.json` (runs 2-3 and `reports/artifacts/cold_latency_stage3_before_run2.json` likewise); finding F6.
- REASONED: what is left of the cold time is the information table (30-40 MB of XML downloaded and
  parsed) plus 5-13 requests spaced >= 0.25 s apart. 895421 still needs 6 submission files: its
  history is split by date into 45 pages, and the window 2025-03-31 .. 2025-08-27 spans five.

## c. Install: one command from GitHub

`uvx --python 3.11 --from git+https://github.com/Serios16/edgar13f-mcp edgar13f-server`, with
`SEC_USER_AGENT` set. Nothing is published to a registry. `tests/tools/install_smoke.sh [ref]`
runs that command with an empty uv cache and `SEC_USER_AGENT` unset (so nothing reaches
sec.gov), does an MCP handshake, and requires the three tools, an `invalid_argument` decline for
a malformed call, and `isError` for a well-formed one (A8).

- MEASURED: SMOKE OK for this branch (resolved to 0cf425b, server 1.1.0), for tag v1.0.0 and for the default branch (both b208c47, server 0.1.0), each in 6-11 s from an empty uv cache with uv 0.8.17; from `PYTHON=python bash tests/tools/install_smoke.sh [ref]`; see `reports/artifacts/install_smoke.txt`.
- REASONED: once this PR is merged, the README command without a ref runs v1.1 code; a tag
  (`@v1.0.0`, later `@v1.1.0` if gate 3 passes) pins a release. The branch run and the merged
  commit have the same `src/`.

It is not run in CI: that would need `uv` on the runner (REGISTER P9).

## d. README

- Gate 2 results next to gate 1 ("identical to gate 1"), the v1.0.0 tag, and the pre-registered
  v1.1 gate (REPORTED by the evaluator).
- Redaction: one neutral sentence ("the author keeps a separate study blind to these
  instruments") and how to switch it off (`EDGAR13F_REDACT=off`, exactly).
- The one-command install, with an MCP client config.
- The latency numbers from b, with the stdio caveat.

## e. REGISTER and version

- REGISTER: new GATES section with "Gate 2 PASS -> v1.0.0 (2026-10-01)" and the v1.1 gate;
  assumptions A17-A21; P5 done for holdings and diff; proposals P7-P9.
- `pyproject.toml` version 1.1.0, and `__version__` (MCP `serverInfo.version`) too (A19). The
  tag v1.0.0 carries package version 0.1.0.

## Regression evidence for the v1.1 gate

The gate needs generated >= 698/700 and 0 leaks on the merged commit. The changes could affect
answers only through b (which filings are read). Evidence that they do not:

- Offline: `tests/unit/test_lazy_fetch.py` turns every fixture manager into an offline EDGAR
  (submissions split into a recent block and older pages with unrelated filings between the
  13Fs, two page layouts, cover pages from the recorded metadata), runs the whole golden grid
  through the new `EdgarSource`, and compares with the v1.0.0 golden. MEASURED: 2 layouts x 3,686 calls, all identical; part of `reports/artifacts/pytest_stage3.txt`.
- MEASURED: the leakage suite (mutant and no-op controls) and the §4 oracle suite are unchanged and pass, in the same CI steps; part of `reports/artifacts/pytest_stage3.txt`.
- Live, SEC Form 13F Data Sets cross-check (P2), same samples and seed as stage 2, new code,
  cold cache. MEASURED: random 250/250 agree (Wilson 95% [0.985, 1.000]), 223 ok answers with 77,074 rows compared; see `reports/artifacts/datasets_crosscheck_stage3.json`.
  MEASURED: restatement strata 208/208 agree (104 before, 104 after), 340,242 rows compared; see `reports/artifacts/datasets_restatement_stage3.json`.
  MEASURED: both equal the stage-2 results (`reports/artifacts/datasets_crosscheck.json`, `reports/artifacts/datasets_restatement.json`): same agreement, same ok/decline split, same rows compared.
- Live, v1.0.0 source vs new source on one shared cache dir, so both read the same EDGAR bytes
  (`tests/tools/equivalence.py`): for every triple of the two samples above, `get_holdings_as_of`,
  `diff_holdings` against the previous quarter, and `list_13f_filings`.
  MEASURED: 1,328 of 1,328 responses byte-identical (456 + 456 + 416 calls over 310 CIKs; outcomes ok, not_yet_filed, notice_only, unknown_cik); the v1.0.0 run needed no request beyond what the new run had cached; see `reports/artifacts/equivalence_stage3.json`.
  REASONED: in this run the v1.0.0 source read information-table rows from the cache the new
  parser wrote, so the parser change is covered by the offline oracle test, not by this run.
- A17's premise: MEASURED: 0 of 80,690 13F submissions (13F-HR, 13F-HR/A, 13F-NT, 13F-NT/A) in the eight data sets (2023q4 to Aug 2025) have a period of report after their filing date, and 0 have a cover period different from the submission period; see `reports/artifacts/period_after_filing.json`.
- REASONED: the one input on which new and old code can differ is a report filed before its own
  period end that sits in a skipped page (pinned by a test). None exists in the data sets above,
  which cover every evaluated period. Visibility still goes through `rules.visible` only.

## SEC access (stage 3)

- MEASURED: 12,619 requests across the 81 request logs of this stage (11,711 www.sec.gov, 908 data.sec.gov), all HTTP 200 (no 403/429), at most 5 completions logged in any 1-second window. From `python tests/tools/request_stats.py <logs>`; see `reports/artifacts/sec_requests_stage3.json`.
- One more request is not in the logs: a data-set zip download that the session proxy cut off
  (F7). The retry succeeded.
- REASONED: as in stage 2, the log records completion times, while the limiter spaces request
  starts >= 0.25 s apart. All live jobs in this session ran one at a time. The install smoke test
  and the stdio checks on warm caches ran with `SEC_USER_AGENT` unset, so they could not reach
  sec.gov. The eight data-set zips came through the same client (User-Agent, limiter, backoff).
  No mirror or other proxy was used besides the environment's egress proxy.

## Findings

| # | Finding | Cause | Action |
|---|---|---|---|
| F6 | Over MCP stdio, a warm 44-50k-row `get_holdings_as_of` takes 6.2-14.5 s with the MCP Python SDK client, but 0.85-1.29 s with a client that reads the line with `readline()` (MEASURED; `stdio_*` fields of `reports/artifacts/cold_latency_stage3_after_run1.json` and the other latency artifacts in b). The SDK 2.2.0 client joins its buffer with every chunk (mcp/client/stdio.py: buffer + chunk, then split on newlines), which is quadratic in the ~40 MB message. Stage 2's A15 ("stdio adds a constant") was wrong for large answers. | MCP SDK client (not this repo) | Measured and reported (A20); upstream report or dropping `structuredContent` for large answers left to the owner (P8). |
| F7 | A truncated transfer (`http.client.IncompleteRead`) is not retried by `SecClient`; it ended one data-set download in this session. Such a request is also missing from `requests.log` (only completed responses are logged). | server (robustness) | Proposal P7; not fixed (out of stage-3 scope). |

## v1.1 gate (pre-registered, not yet run)

Tag v1.1.0 only if gate 3, run on the merged commit, passes every primary gate with generated
>= 698/700 and 0 leaks. The PR is not merged by the builder.
