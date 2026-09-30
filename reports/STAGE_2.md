# Stage 2 report: hardening

Labels: each claim is tagged measured, reported, reasoned or assumed (upper-case tag on the line); untagged = assumed.
Artifacts are in `reports/artifacts/`. Offline results come from the branch head. Live results
come from sec.gov with `SEC_USER_AGENT` set, a <= 5 req/s limit, and on-disk caches outside the repo.

No file under `src/` changed in stage 2 (970 lines, same as stage 1).
MEASURED: `python tests/checks/size_budget.py .` passes; see `reports/artifacts/size_budget.txt`.

## a. Stage 1 report and rulings D1-D3

- `reports/STAGE_1.md` now records D1 (keep `unknown_cik`), D2 (redact; lost points are an
  accepted cost) and D3 (keep `typing-extensions`, PSF). None is open.
- Erratum: stage 1 said the fixtures held a zero-row restatement. They did not; the erratum is
  in `reports/STAGE_1.md`. MEASURED: no stage-1 rows file is empty, and the data sets contain
  no zero-row RESTATEMENT in the window (survey with `tests/tools/datasets_crosscheck.py` loaders).

## b. Restatement hardening (contract §4)

New suite `tests/unit/test_restatement.py`:

| Part | What | Cases |
|---|---|---|
| Oracle | `rules.resolve` vs an independent oracle written from the §4 text. It covers every sequence of 1-4 HR/HR-A filings (kinds O/R/N/UNSPECIFIED, <= 1 ORIGINAL), same or different day, amendment_no in order / reversed / null, accession order in order / reversed, with and without a notice, and 4 `as_of` values | 169,152 comparisons |
| Controls | 5 planted rule mutants (accession-only ordering, NULLS LAST, UNSPECIFIED as NEW HOLDINGS, visibility ignored, supplements before the base); each must be detected | 5 of 5 detected |
| Synthetic manager | `tests/fixtures/synthetic/9900000001/`: a zero-row restatement; three amendments on one day with amendment_no order opposite to accession order; UNSPECIFIED; a restatement after NEW HOLDINGS; a restatement with lowercase CUSIPs (filter, consolidation, `diff_holdings`); a notice restatement | 22 tests |
| Blocklist in restatements (D2) | Synthetic XML parsed in memory: rows redacted, the citation is still the restatement, a fully redacted restatement still supersedes the original, a filter on a blocked CUSIP gives `ok` with no rows, and an over-matched row disappears at the restatement; plus a planted failure | 5 tests |
| Recorded edge cases | 7 managers recorded from EDGAR (redacted at parse): same-day ORR/ORN, ONRN, ONRR, ONR, a lowercase-CUSIP restatement. Expected citations are derived from the SEC Form 13F Data Sets metadata (`tests/fixtures/section4_expected.json`) | 82 cases |

- MEASURED: 116 of 116 pass; full suite 228 passed, 1 skipped (root-only skip). From `python -m pytest -q tests`; see `reports/artifacts/pytest_stage2.txt`.
- MEASURED: the leakage suite now covers 981 cases with 0 violations; the mutant finds 8,663 and the no-op 0. From `python -m tests.tools.leakage_summary`; see `reports/artifacts/leakage_summary_stage2.json`.
- MEASURED: the offline run of the planted mutants is in CI; the step list is in `.github/workflows/invariants.yml`.

Findings and their cause:

| # | Finding | Cause |
|---|---|---|
| F1 | A restatement whose rows are all removed by the blocklist gives `ok` with no rows and cites the restatement, not the original. This follows §4, and a grader item about those CUSIPs would miss. | blocklist (D2, accepted cost) |
| F2 | A row that passes the blocklist in the original can be removed in the restatement when its title changes (e.g. `COM` to `COM UNIT` for an energy issuer). The CUSIP then looks "removed" at the restatement. | blocklist (D2, accepted cost; over-dropping is allowed) |
| F3 | Data-set oracle vs server for managers whose first 13F is filed after `as_of`: `unknown_cik` vs `not_yet_filed`. | Neither. It was a gap in the test harness; the server follows D1. The harness now expects `unknown_cik` |
| F4 | The server disagreed with §4 in no case: none of the rule tests, the 82 recorded cases or the restatement strata below | n/a |

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

P2_PLACEHOLDER

## e. Cold-cache latency (measure only)

LATENCY_PLACEHOLDER

## f, g. README, MAP, REGISTER

- `README.md` is rewritten for a public audience. It covers what the server does and why
  point-in-time matters, install and run, the three tools, limits, the evaluation design, the
  gate 1 results (REPORTED) and the licence.
- `MAP.md` lists the new tests, fixtures, tools and the CI probe.
- `REGISTER.md`: P1 and P2 are done. New assumptions A13-A16 (cross-check oracle, synthetic
  CIK, how latency is measured, offline probe). New proposals P4 (the rate-limit lock is held
  through the whole response) and P5 (cover pages are fetched lazily). Both are out of scope
  for a measure-only stage.

## Gate 1 (REPORTED by the evaluator)

All primary gates PASS. Generated 698/700 (one miss each in restatement_before and
restatement_after). Citation validity 669/671. Leakage 0 over 3,114. Curated 34/34, declines 6/6.
