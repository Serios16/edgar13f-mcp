# REGISTER

Decisions, assumptions and proposals for edgar13f-mcp. Trigger "stage gate" = revisit
at the next stage gate review.

## DECISION NEEDED

| ID | Topic | Issue | Default in code (reversible) | Trigger |
|---|---|---|---|---|
| D1 | Contract §5.2 vs §6 | §5.2 says an empty `filings` array is a valid success "when the CIK is a known 13F filer but nothing is visible yet"; §6 says `unknown_cik` when the CIK "has never filed a Form 13F … on or before `as_of`". For a manager whose first 13F is after `as_of` both apply. | Decline `unknown_cik` (the reading that lets nothing filed after `as_of` influence the response, §3). Work on this branch point stopped here; the empty-array path is unreachable. | stage gate |
| D2 | Blocklist vs contract §5.3/§7 | Hard rule 2 redacts rows for gold / US-energy-sector / S&P 500 funds and UCITS copies before any processing. Contract §7 grades exact values and citation validity per CUSIP, so any grader item about a redacted CUSIP will get no rows (or a diff without that key). Redaction also drops over-matched rows (e.g. equity units named "… ENERGY … UNIT"). | Redact (hard rule wins over contract). No change to `contracts/`. | stage gate |
| D3 | Dependency licenses (rule 4) | The MCP Python SDK 2.x (required by rule 5) and pydantic depend on `typing-extensions`, licensed PSF-2.0, which is outside MIT/Apache/BSD. Every other runtime dependency is MIT, Apache-2.0 or BSD-3-Clause (`reports/artifacts/license_audit.txt`). | Keep it (no SDK 2.x install is possible without it). | stage gate |

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

## PROPOSALS (out of scope; not done)

| ID | Proposal |
|---|---|
| P1 | Add the unprivileged-user probe (`tests/tools/unprivileged_probe.sh`) as a CI step (needs `sudo useradd` on the runner). |
| P2 | Stage 2: cross-check holdings against the SEC Form 13F Data Sets (the source named in §3) for a sample of (cik, period, as_of). |
| P3 | Note: the brief names `PREREG_COMMITMENT.md` at the repo root; it is at `contracts/PREREG_COMMITMENT.md` and is treated as read-only there. No change made. |
