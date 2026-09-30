# Stage 2 report: hardening

Labels: each claim is tagged measured, reported, reasoned or assumed (upper-case tag on the line); untagged = assumed.
Artifacts are in `reports/artifacts/`. Offline results come from the branch head. Live results
come from sec.gov with `SEC_USER_AGENT` set, a <= 5 req/s limit, and on-disk caches outside the repo.

`src/` changed only for finding F5 (+19 lines, 989 in total).
MEASURED: `python tests/checks/size_budget.py .` passes; see `reports/artifacts/size_budget.txt`.

## a. Stage 1 report and rulings D1-D3

- `reports/STAGE_1.md` now records D1 (keep `unknown_cik`), D2 (redact; lost points are an
  accepted cost) and D3 (keep `typing-extensions`, PSF). None is open.
- Erratum: stage 1 said the fixtures held a zero-row restatement. They did not; the erratum is
  in `reports/STAGE_1.md`. The synthetic manager (b) now covers that case.
- MEASURED: no rows file among the stage-1 fixtures is empty; each file was checked; the fixtures are in `tests/fixtures/`.
- ASSUMED (scratch survey, no committed artifact): the data sets contain no RESTATEMENT with zero
  information-table rows among the evaluated periods.

## b. Restatement hardening (contract §4)

New suite `tests/unit/test_restatement.py`:

| Part | What | Cases |
|---|---|---|
| Oracle | `rules.resolve` vs an independent oracle written from the §4 text. It covers every sequence of 1-4 HR/HR-A filings (kinds O/R/N/UNSPECIFIED, <= 1 ORIGINAL), same or different day, amendment_no in order / reversed / null, accession order in order / reversed, with and without a notice, and 4 `as_of` values | 169,152 comparisons |
| Controls | 5 planted rule mutants (accession-only ordering, NULLS LAST, UNSPECIFIED as NEW HOLDINGS, visibility ignored, supplements before the base); each must be detected | 5 of 5 detected |
| Synthetic manager | `tests/fixtures/synthetic/9900000001/`: a zero-row restatement; three amendments on one day with amendment_no order opposite to accession order; UNSPECIFIED; a restatement after NEW HOLDINGS; a restatement with lowercase CUSIPs (filter, consolidation, `diff_holdings`); a notice restatement | 22 tests |
| Blocklist in restatements (D2) | Synthetic XML parsed in memory: rows redacted, the citation is still the restatement, a fully redacted restatement still supersedes the original, a filter on a blocked CUSIP gives `ok` with no rows, and an over-matched row disappears at the restatement; plus a planted failure | 5 tests |
| Recorded edge cases | 7 managers recorded from EDGAR (redacted at parse): same-day ORR/ORN, ONRN, ONRR, ONR, a lowercase-CUSIP restatement. Expected citations are derived from the SEC Form 13F Data Sets metadata (`tests/fixtures/section4_expected.json`) | 82 cases |

- MEASURED: 116 of 116 pass; full suite 230 passed, 1 skipped (root-only skip). From `python -m pytest -q tests`; see `reports/artifacts/pytest_stage2.txt`.
- MEASURED: the leakage suite now covers 981 cases with 0 violations; the mutant finds 8,663 and the no-op 0. From `python -m tests.tools.leakage_summary`; see `reports/artifacts/leakage_summary_stage2.json`.
- The rule mutants and the oracle run in CI in the "Unit tests" step of `.github/workflows/invariants.yml`.

Findings and their cause:

| # | Finding | Cause |
|---|---|---|
| F1 | A restatement whose rows are all removed by the blocklist gives `ok` with no rows and cites the restatement, not the original. This follows §4. REASONED: a grader item about those CUSIPs would miss. | blocklist (D2, accepted cost) |
| F2 | A row that passes the blocklist in the original can be removed in the restatement when its title changes (e.g. `COM` to `COM UNIT` for an energy issuer). The CUSIP then looks "removed" at the restatement. | blocklist (D2, accepted cost; over-dropping is allowed) |
| F3 | Data-set oracle vs server for managers whose first 13F is filed after `as_of`: `unknown_cik` vs `not_yet_filed`. | Neither. It was a gap in the test harness; the server follows D1. The harness now expects `unknown_cik` |
| F4 | The server disagreed with §4 in no case: none of the rule tests, the 82 recorded cases or the 208 restatement-strata triples in d | n/a |
| F5 | A filer's information table named `index.xml` is shadowed by EDGAR's directory listing, so 0 rows were returned (found by P2, see d) | **server**, fixed |

The two hidden gate-1 misses were not investigated item by item, as instructed.

## c. P1: unprivileged-user probe in CI

`tests/tools/unprivileged_probe.sh --offline` runs in the `invariants` job (job name unchanged;
still only actions/checkout and actions/setup-python; sudo is used on the runner). It creates a
separate user and a read-only copy of the checkout. For three cache-dir cases (env set, HOME
writable, HOME unwritable) it runs the server over stdio as that user. It asserts an
`invalid_argument` decline and an `isError` live call (no `SEC_USER_AGENT`; A8). It fails if the
user creates any file or directory outside the expected cache dir or can write to the checkout.
A second step plants a stray write and requires the probe to fail.

- MEASURED: local run, PROBE OK, and the planted run fails as required. From `sudo env PYTHON=python3.11 bash tests/tools/unprivileged_probe.sh --offline`; see `reports/artifacts/unprivileged_run_offline.txt`.
- REPORTED: CI run 36725393258 (commit a20e120) passed both steps; the log shows `PROBE OK (offline)` and the planted `PROBE FAIL ... /tmp/edgar13f-planted`. Later runs are linked in the PR.

## d. P2: cross-check against the SEC Form 13F Data Sets

Script: `tests/tools/datasets_crosscheck.py`. It runs at test time only, not in CI, and the server
never reads the data sets. The data sets were downloaded to a scratch dir outside the repo and are
not committed. They are the six SEC Form 13F Data Sets covering filings dated 2024-03-01 to
2025-08-31, plus 2023q4 and Jan–Feb 2024, which are used only to tell whether a CIK had already
filed a 13F (ruling D1). The script samples (cik, period) uniformly over pairs in the data sets with
period 2024-03-31 … 2025-06-30, leaving out the §4 never-evaluated cases, and draws `as_of`
uniformly from [first filing − 14 days, 2025-08-27] (seed 20260930). It calls `get_holdings_as_of`
on live EDGAR and compares the answer with §4 applied to the data sets: the decline reason, or
`source_accessions` + `filing_date` + the row multiset (CUSIP case-insensitive, value, shares,
SH/PRN, put/call). Data-set rows pass through the same blocklist first (A13). The artifacts hold
counts, accessions and causes only.

| Run | Agree / n | Rate | Wilson 95% | Disagreements by cause |
|---|---|---|---|---|
| Random, first pass (server before the fix below) | 249 / 250 | 0.996 | [0.978, 0.999] | 1 × rows: **server** |
| Random, after the fix (same triples) | 250 / 250 | 1.000 | [0.985, 1.000] | none |
| Restatement strata (before/after each amendment date; 84 (cik, period) pairs incl. every restatement-after-NEW-HOLDINGS and multi-amendment-same-day pair) | 208 / 208 | 1.000 | [0.982, 1.000] | none (104 before, 104 after) |

- MEASURED: first pass. From `python -m tests.tools.datasets_crosscheck run --n 250 --seed 20260930`; see `reports/artifacts/datasets_crosscheck_prefix.json`.
- MEASURED: after the fix, 223 ok answers (77,074 rows compared) and 27 declines; 167 of the 250 triples had data-set rows removed by the blocklist, identically on both sides. See `reports/artifacts/datasets_crosscheck.json`.
- MEASURED: restatement strata, 188 ok answers (340,242 rows compared) and 20 declines. From `... run --strata restatement --n 20`; see `reports/artifacts/datasets_restatement.json`.
- MEASURED: an earlier scoring of the strata, without the 2023q4 and Jan–Feb 2024 data sets, showed 4 cases of cause `dataset_coverage` (server `not_yet_filed`, oracle `unknown_cik`). All 4 CIKs had filed 13Fs from 2023-10-16 to 2024-02-13, so the server was right and the harness was not; the rescored run is in `reports/artifacts/datasets_restatement.json`.
- REASONED: each run is one sample, so the claim is the Wilson bound, not the point rate. The strata runs used the server from before the F5 fix; none of their filings is affected by F5 (208/208 either way).

**Server finding F5 (fixed).** For accession 0001012975-25-000102 the server returned 0 rows,
while the data sets hold 8 rows after redaction. The filer named its information table `index.xml`.
At that URL EDGAR serves its own directory listing, so the table was never seen. Cause:
**server** (`EdgarSource.rows`). The fix is in `src/edgar13f/sources.py` and `parse.py`
(+19 lines): when no XML item of the filing is an information table, the server reads the
`<XML>` documents of the full submission text (`<accession>.txt`). The blocklist still applies
to each row first, and the text is never cached. Tests are in `tests/invariants/test_blocklist.py`;
the new one fails on the old code. Caches written before the fix may still hold `[]` for such a
filing (REGISTER P6).

## e. Cold-cache latency (measure only)

Tool: `tests/tools/cold_latency.py` (A15). It picks the 5 largest 13F-HRs for 2025-03-31 by rows
after redaction in the 01mar2025–31may2025 data set. It calls `get_holdings_as_of(cik, 2025-03-31,
as_of=2025-08-27)` in-process on an empty cache dir, then calls it again warm. No tuning was done.

| CIK | Visible 13F filings | Cold s | Cold requests | Warm s | Rows returned |
|---|---|---|---|---|---|
| 2012383 | 4 | 7.1 | 9 | 0.15 | 50,158 |
| 319933 | 6 | 6.7 | 9 | 0.11 | 49,594 |
| 1761755 | 28 | 14.0 | 31 | 0.11 | 44,548 |
| 895421 | 154 | 51.4 | 118 | 0.23 | 44,192 |
| 1776033 | 20 | 9.0 | 23 | 0.01 | 1,599 (a RESTATEMENT filed the next day supersedes the 34,332-row original; this is §4-correct and matches the data sets) |

- MEASURED: 5 of 5 answers are ok and every request returned HTTP 200. From `python -m tests.tools.cold_latency --zip <01mar2025-31may2025 zip> --n 5`; see `reports/artifacts/cold_latency.json`.
- REASONED: cold time is driven by the request count, one cover page per visible 13F of any period (REGISTER P5), at about 0.4 s per request with the lock held through each response (P4). The information-table size adds only a few seconds even at 50k rows. Warm calls take 0.01–0.23 s.

## SEC access (stage 2)

- MEASURED: 11,645 requests across all stage-2 logs (11,211 www.sec.gov, 434 data.sec.gov): 11,554 × HTTP 200 and 91 × HTTP 429. The 429s came in two bursts (14:16 and 14:21 UTC) while the P2 runs were sending about 2.5 req/s, and 91 of 91 later succeeded after backoff. At most 5 requests were logged in any 1-second window. From `python tests/tools/request_stats.py <logs>`; see `reports/artifacts/sec_requests_stage2.json`.
- REASONED: the log records completion times, while the limiter spaces request starts ≥ 0.25 s apart, so up to 5 completions can fall in one second; that is within the ≤ 5 req/s rule. The cause of the 429s at 2.5 req/s is unclear; a shared egress IP behind the session proxy is plausible but not verified.
- The data-set zips (8 files) were fetched through the same client, with the same User-Agent, limiter and backoff. Nothing used a mirror or proxy other than the environment's egress proxy.

## f, g. README, MAP, REGISTER

- `README.md` is rewritten for a public audience. It covers what the server does and why
  point-in-time matters, install and run, the three tools, limits, the evaluation design, the
  gate 1 results (REPORTED) and the licence.
- `MAP.md` lists the new tests, fixtures, tools and the CI probe.
- `REGISTER.md`: P1 and P2 are done. New assumptions A13-A16 (cross-check oracle, synthetic
  CIK, how latency is measured, offline probe). New proposals P4 (the rate-limit lock is held
  through the whole response) and P5 (cover pages are fetched lazily). Both are out of scope
  for a measure-only stage. P6: caches written before the F5 fix are not invalidated.

## Gate 1 (REPORTED by the evaluator)

All primary gates PASS. Generated 698/700 (one miss each in restatement_before and
restatement_after). Citation validity 669/671. Leakage 0 over 3,114. Curated 34/34, declines 6/6.
