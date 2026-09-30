# REGISTER

Decisions, assumptions and proposals for edgar13f-mcp. Trigger "stage gate" = revisit
at the next stage gate review.

## DECISION NEEDED

None open.

## RULINGS (2026-09-29, orchestrator; recorded before any grader result exists)

| ID | Topic | Ruling | Reasoning / standing rule |
|---|---|---|---|
| D1 | Contract §5.2 vs §6 (a manager whose first 13F is filed after `as_of`) | Keep `unknown_cik`. | §3 and §6 are normative and agree: nothing filed after `as_of` may influence a response, and a CIK that has not filed a Form 13F on or before `as_of` is `unknown_cik`. The empty-array sentence in §5.2 cannot be reached under them. Test: `tests/unit/test_tools.py::test_first_13f_after_as_of_is_unknown_cik`. |
| D2 | Blocklist vs contract §5.3/§7 exact-match grading | Redact. | Hard rule 2 outranks exact-match score. Lost points on grader items about redacted CUSIPs (including over-matched rows) are an **accepted cost**. Standing rule for all stages: never narrow the blocklist to recover points. |
| D3 | `typing-extensions` (PSF-2.0), a transitive dependency of MCP SDK 2.x and pydantic | Keep it. | Rule 4 in CLAUDE.md is amended to "permissive OSI licences (MIT/Apache/BSD/PSF/ISC)". `tests/tools/license_audit.py` accepts that list and its output (`reports/artifacts/license_audit.txt`) shows every runtime dependency as `ok`. |

## ASSUMED

| ID | Assumption | Why / alternative | Trigger |
|---|---|---|---|
| A1 | `period_of_report` = cover page `reportCalendarOrQuarter`, else header `periodOfReport`, else the submissions index `reportDate`. | The contract calls the period the "report for the calendar year or quarter ended" date. In the fixture sample, 598 of 598 XML filings had cover == `reportDate` (`reports/artifacts/period_consistency.json`). | stage gate |
| A2 | `is_amendment` = submission type ends with `/A`. | Matches §4's classification by submission type. | stage gate |
| A3 | If only `NEW HOLDINGS` amendments are visible for a period (no ORIGINAL/RESTATEMENT), decline `not_yet_filed`. | §4 does not define a base for this case. | stage gate |
| A4 | Pre-XML (text) 13F filings: listed with metadata from the EDGAR submissions index; `amendment_no`, `amendment_type`, `report_type`, `filing_manager_name` are `null`; `get_holdings_as_of` returns zero rows for them. | Outside the evaluated window (2024-03-31 … 2025-06-30). | stage gate |
| A5 | `filing_manager_name` is the cover-page name as filed, not EDGAR's current entity name. | "as on the cover page". | stage gate |
| A6 | Strict JSON types: a numeric `cik`, a non-array `cusip`, a non-string `position_type` → `invalid_argument`. Exact-duplicate CUSIPs → `invalid_argument` (schema `uniqueItems`); case-only duplicates are accepted. | Schema types. | stage gate |
| A7 | A cached submissions JSON is reused for `as_of` only if it was fetched ≥ 2 days after `as_of`; documents of a filing (cover, index, redacted rows) are cached indefinitely. | Filings do not change after acceptance; the 2-day margin covers after-hours acceptance dated the next day. | stage gate |
| A8 | sec.gov unreachable / `SEC_USER_AGENT` unset / retries exhausted → `isError: true` (internal failure), not a decline. | §5.1 reserves `isError` for transport/internal failures; no decline reason fits. | stage gate |
| A9 | The ≤ 5 req/s limit is enforced across all processes that share a cache dir (fcntl lock on `ratelimit.lock`, request starts ≥ 0.25 s apart, lock held through the send). Processes with different cache dirs are not coordinated. | Hard rule 3 "global". | stage gate |
| A10 | `EDGAR13F_FIXTURE_DIR` switches the server to recorded fixtures (used by the offline stdio test). | Test hook; unset in normal use. | stage gate |
| A11 | CLAUDE.md contains the brief's HARD RULES and CLAIMS AND UNCERTAINTY sections verbatim. | "these rules" read as both rule blocks. | stage gate |
| A12 | CUSIP comparison in `diff_holdings` consolidation keys is case-insensitive; the CUSIP returned is as filed (period B preferred). | PREREG Amendment 1 (case-insensitive comparison). | stage gate |
| A13 | P2 cross-check: the expected answer is §4 applied to the data sets' SUBMISSION/COVERPAGE metadata (period = COVERPAGE `REPORTCALENDARORQUARTER`), rows = INFOTABLE after the blocklist, compared as a multiset of (cusip case-insensitive, value, shares, sh_prn, put_call). `unknown_cik` is expected when the data sets hold no 13F by the CIK on or before `as_of`; a server `not_yet_filed` there is cause `dataset_coverage` (the data sets start 2024-03-01). (cik, period) pairs that §4 says are never evaluated (UNSPECIFIED, >1 ORIGINAL) are not sampled. | Test-time only; the server never reads the data sets. | stage gate |
| A14 | Synthetic fixture manager uses CIK 9900000001 (above every assigned EDGAR CIK) and lives under `tests/fixtures/synthetic/`. Blocklisted rows for restatement tests are built in memory from the synthetic rows in `tests/invariants/test_blocklist.py`, never stored. | Hard rule 2: fixtures must not contain blocked rows. | stage gate |
| A15 | Cold-cache latency is measured in-process (`tools.call` on `EdgarSource`, empty cache dir), not over stdio; the stdio layer adds a constant. Filers = top 5 13F-HR for 2025-03-31 by rows after redaction. | Measure only (stage 2 scope e). | stage gate |
| A16 | CI probe runs `--offline`: `SEC_USER_AGENT` unset, so the live call must be `isError: true` (A8) while a malformed call must be an `invalid_argument` decline; the cache dir is still created. The live-mode probe stays a manual tool. | CI stays offline (no sec.gov). | stage gate |

## PROPOSALS (out of scope; not done)

| ID | Proposal |
|---|---|
| P1 | DONE in stage 2: the probe runs offline in the `invariants` job, with a planted-failure control. |
| P2 | DONE in stage 2 (test time only): `tests/tools/datasets_crosscheck.py`; results in `reports/STAGE_2.md`. |
| P3 | Note: the brief names `PREREG_COMMITMENT.md` at the repo root; it is at `contracts/PREREG_COMMITMENT.md` and is treated as read-only there. No change made. |
| P4 | Throughput: `SecClient._throttled` holds the rate-limit lock until the whole response is read, so measured throughput is ~2.5 req/s, not the permitted 4. Releasing the lock after the response headers would keep the <= 5 req/s start spacing. Not done (stage 2 is measure-only). |
| P6 | Caches written before the F5 fix (stage 2) may hold `rows/<accession>.json` = `[]` for a filing whose information table is named `index.xml`. The fix does not invalidate old caches; delete `<cache>/rows/` to refresh. A versioned rows dir would do it automatically. Not done: the smallest reversible change was preferred. |
| P5 | Cold latency: `EdgarSource.filings` fetches the cover page of every visible 13F of every period, so a first call costs one request per historical filing. Fetching covers lazily (only for the requested period, and for `list_13f_filings`) would cut cold latency. Not done (measure-only). |
