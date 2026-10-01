# Stage 3 report: release

Labels: each claim is tagged measured, reported, reasoned or assumed (upper-case tag on the line);
untagged = assumed. Artifacts are in `reports/artifacts/`. Live results come from sec.gov with
`SEC_USER_AGENT` set, the <= 5 req/s limiter and on-disk caches outside the repo. The acceptance
criteria were fixed by the brief before any work. Item-level gate results were not looked for.

`src/` changed in 6 files (+107/-53 lines against v1.0.0; 1,043 lines in total; no file over 250).
MEASURED: `python tests/checks/size_budget.py .` passes; see `reports/artifacts/size_budget.txt`.
MEASURED: full suite PYTEST_SUMMARY; see `reports/artifacts/pytest_stage3.txt`.

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
- The server was never run with `off` against live SEC data or recorded fixtures, in this session
  or in CI. `tests/conftest.py` unsets the variable for every test.
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

LATENCY_SECTION

## c. Install: one command from GitHub

`uvx --python 3.11 --from git+https://github.com/Serios16/edgar13f-mcp edgar13f-server`, with
`SEC_USER_AGENT` set. Nothing is published to a registry. `tests/tools/install_smoke.sh [ref]`
runs that command with an empty uv cache and `SEC_USER_AGENT` unset (so nothing reaches
sec.gov), does an MCP handshake, and requires the three tools, an `invalid_argument` decline for
a malformed call, and `isError` for a well-formed one (A8).

INSTALL_LINES

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
- Leakage suite and the §4 oracle suite unchanged and passing (same CI steps).
- Live, SEC Form 13F Data Sets cross-check (P2), same samples and seed as stage 2, new code,
  cold cache. MEASURED: random 250/250 agree (Wilson 95% [0.985, 1.000]), 223 ok answers with 77,074 rows compared; see `reports/artifacts/datasets_crosscheck_stage3.json`.
  MEASURED: restatement strata 208/208 agree (104 before, 104 after), 340,242 rows compared; see `reports/artifacts/datasets_restatement_stage3.json`.
  Both equal the stage-2 results.
- Live, v1.0.0 vs new source on one shared cache dir (same EDGAR bytes): EQUIVALENCE_LINES
- A17's premise: MEASURED: 0 of 80,690 13F submissions (13F-HR, 13F-HR/A, 13F-NT, 13F-NT/A) in the eight data sets (2023q4 to Aug 2025) have a period of report after their filing date, and 0 have a cover period different from the submission period; see `reports/artifacts/period_after_filing.json`.
- REASONED: the one input on which new and old code can differ is a report filed before its own
  period end that sits in a skipped page (pinned by a test). None exists in the data sets above,
  which cover every evaluated period. Visibility still goes through `rules.visible` only.

SEC_LINES

## Findings

| # | Finding | Cause | Action |
|---|---|---|---|
| F6 | Over MCP stdio, a warm 44-50k-row `get_holdings_as_of` takes 11-16 s with the MCP Python SDK client, but 1.1 s with a client that reads the line with `readline()`. The SDK 2.2.0 client joins its buffer with every chunk (`mcp/client/stdio.py`, `(buffer + chunk).split("\n")`), which is quadratic in the ~40 MB message. Stage 2's A15 ("stdio adds a constant") was wrong for large answers. | MCP SDK client (not this repo) | Measured and reported (A20); upstream report or dropping `structuredContent` for large answers left to the owner (P8). |
| F7 | A truncated transfer (`http.client.IncompleteRead`) is not retried by `SecClient`; it ended one data-set download in this session. Such a request is also missing from `requests.log` (only completed responses are logged). | server (robustness) | Proposal P7; not fixed (out of stage-3 scope). |

## v1.1 gate (pre-registered, not yet run)

Tag v1.1.0 only if gate 3, run on the merged commit, passes every primary gate with generated
>= 698/700 and 0 leaks. The PR is not merged by the builder.
