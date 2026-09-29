# Stage 1 report: edgar13f MCP server

Labels: each claim is tagged measured, reported, reasoned or assumed (upper-case tag on the line).
Artifacts live in `reports/artifacts/`, generated locally on the branch head, with no network
except where a line says otherwise.

## What was built

- A stdio MCP server (`python -m edgar13f.server`) on the official MCP Python SDK 2.x (2.2.0)
  low-level `Server`, with the three contract tools `list_13f_filings`,
  `get_holdings_as_of` and `diff_holdings`. There are 11 modules in `src/edgar13f/`
  (see `MAP.md`).
- Point-in-time: `rules.visible` (filing_date <= as_of) is the only visibility check.
  Everything that lists, resolves or fetches goes through it.
- Amendments (§4): ordering is (filing_date, amendment_no NULLS FIRST, accession). The base is
  the last ORIGINAL/RESTATEMENT and the supplements are the later NEW HOLDINGS amendments.
  UNSPECIFIED is treated as RESTATEMENT.
- Declines: all six reasons, with the §6 precedence. Every response carries the literal
  disclaimer. Every success carries the accession number(s). `list_13f_filings` returns an
  `edgar_url` for each filing.
- SEC client: the User-Agent comes from `$SEC_USER_AGENT`. Request starts are spaced
  >= 0.21 s apart across processes (fcntl lock). There is exponential backoff on
  403/429/5xx/network errors and on HTML pages served instead of data. Responses go to an
  on-disk cache, and every request is logged in `requests.log`.
- Blocklist: the patterns and CUSIPs are applied to each info-table row before any other
  field is read. The raw info table is never cached; only redacted rows are.
- Offline fixtures for 17 managers (`tests/fixtures/`). They cover 13F-HR, RESTATEMENT and
  NEW HOLDINGS amendments, a combination report, a zero-row restatement, NT-only filers
  and NT/A filings.
- The `invariants` CI job (`.github/workflows/invariants.yml`). It uses only
  actions/checkout and actions/setup-python. The tests refuse outbound sockets.

## Checks and controls

| Check | Result | Control (planted failure) | Control result |
|---|---|---|---|
| Unit tests (`tests/unit`) | pass | `test_unit_test_runner_planted_failure` runs a failing test file | pytest exits non-zero, as expected |
| Leakage suite | 603 cases, 0 violations | mutant: `rules.visible` always true | 4,387 violations (>= 1 required) |
| Leakage no-op control | wrapper around `rules.visible` | n/a | 0 violations |
| Blocklist (31 synthetic blocked rows, 7 benign) | all blocked rows dropped, benign rows kept, fixtures have 0 hits | `test_planted_failure_disabled_blocklist_is_detected` | all 31 survive and are detected |
| Size budget | 968 lines in src/, max 137 per file | a 251-line file; 7 × 240 lines | both flagged |
| MAP check | all 11 modules listed | module missing from MAP | flagged |
| Claims check | every measured line names a committed path | a missing path and a line with no path | both flagged |
| Offline guard | sockets refused | `test_offline_guard_blocks_network` | connection refused |

- MEASURED: full offline suite, 110 passed and 1 skipped (a root-only skip), from `python -m pytest -q tests`; see `reports/artifacts/pytest_all.txt`.
- MEASURED: leakage cases, tool calls, and mutant/no-op violation counts, from `python -m tests.tools.leakage_summary`; see `reports/artifacts/leakage_summary.json`.
- MEASURED: size budget of 968 lines total, from `python tests/checks/size_budget.py .`; see `reports/artifacts/size_budget.txt`.
- MEASURED: the static checks pass in the committed tree; the planted failures are in `tests/invariants/test_checks.py`.
- REPORTED: the result of the CI run is linked in the PR description, not here, because this report is committed before the run exists.

## SEC access

- MEASURED: 919 logged requests to sec.gov (21 to data.sec.gov, 898 to www.sec.gov), all HTTP 200, with at most 4 in any 1-second window. From `python tests/tools/request_stats.py <logs>`; see `reports/artifacts/sec_requests.json`.
- REASONED: these requests are not in the logs above: 2 manual `curl` reachability probes made before the client existed, and 9 requests from a first unprivileged-user probe whose cache was wiped. The total is therefore 930.
- MEASURED: the server runs as a separate unprivileged user that can only read its checkout. It writes only to `$EDGAR13F_CACHE_DIR`, then `~/.cache/edgar13f`, then `/tmp/edgar13f-<uid>`, and a write into the checkout is denied. From `bash tests/tools/unprivileged_probe.sh`; see `reports/artifacts/unprivileged_run.txt`.
- MEASURED: the cover-page period equals EDGAR `reportDate` for 598 of 598 fixture XML filings. From `python tests/tools/period_consistency.py` (cached documents); see `reports/artifacts/period_consistency.json`.
- MEASURED: every runtime dependency is MIT, Apache-2.0 or BSD-3-Clause except `typing-extensions` (PSF-2.0). From `python tests/tools/license_audit.py`; see `reports/artifacts/license_audit.txt`.

## REGISTER entries

- DECISION NEEDED
  - D1: contract §5.2 empty array vs §6 `unknown_cik`. The default is `unknown_cik`.
  - D2: the blocklist conflicts with exact-match grading of the redacted CUSIPs. The default is to redact.
  - D3: `typing-extensions` is PSF-2.0 and comes in through the MCP SDK and pydantic. The default is to keep it.
- ASSUMED: A1–A12 (period source, is_amendment, a base made only of NEW HOLDINGS, pre-XML filings,
  manager name, strict types, cache freshness, isError on SEC outage, rate-limit scope, fixture hook,
  CLAUDE.md scope, case-insensitive diff keys). Each has the trigger "stage gate".
- Proposals: P1 (unprivileged probe in CI), P2 (cross-check against the SEC Form 13F Data Sets),
  P3 (note on the PREREG path).

## Deviations

- None were made silently. D3 is a conflict between hard rules 4 and 5, and it is flagged rather than resolved.
- ASSUMED: redacting blocklisted rows will cost points on any grader item about those CUSIPs (D2).

## Proposed stage 2

1. Resolve D1–D3.
2. Cross-check a sample of `get_holdings_as_of` answers against the SEC Form 13F Data Sets
   (SUBMISSION, COVERPAGE, INFOTABLE) for the evaluation window.
3. Add more fixtures with UNSPECIFIED amendments and same-day multi-amendment ordering.
4. Run the unprivileged-user probe in CI (P1).
5. Measure cold-cache latency for large filers.
