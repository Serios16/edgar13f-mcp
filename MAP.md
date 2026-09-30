# MAP

## Modules (`src/edgar13f/`)

| Module | Role |
|---|---|
| `src/edgar13f/__init__.py` | Package version and the mandatory `DISCLAIMER` string (§5.1). |
| `src/edgar13f/config.py` | Cache dir resolution (`$EDGAR13F_CACHE_DIR` → `$XDG_CACHE_HOME/edgar13f` or `~/.cache/edgar13f` → per-user temp dir) and `$SEC_USER_AGENT`. |
| `src/edgar13f/sec_client.py` | Only code that talks to sec.gov: User-Agent, ≤5 req/s cross-process limiter, exponential backoff (403/429/5xx/network/HTML-instead-of-data), on-disk cache, `requests.log`. |
| `src/edgar13f/blocklist.py` | Hard rule 2: issuer-name/title patterns + CUSIP list; `is_blocked()`. |
| `src/edgar13f/parse.py` | Cover-page parser and information-table parser; the blocklist is applied to each row before any other field is read. |
| `src/edgar13f/rules.py` | `Filing` record, §3 `visible()` (single enforcement point), §4 `resolve()` (base + supplements), §5.2 filing record. |
| `src/edgar13f/sources.py` | `EdgarSource` (submissions JSON → filings, primary_doc.xml → cover, index.json + info table → redacted rows cached as JSON) and `FixtureSource` (offline). |
| `src/edgar13f/validate.py` | §2 input conventions and §6 decline precedence for argument-level reasons. |
| `src/edgar13f/tools.py` | The three tools (§1, §5, §6): envelopes, declines, consolidation for `diff_holdings`. |
| `src/edgar13f/schemas.py` | Tool input schemas advertised over MCP (inlined from `contracts/tools.schema.json`). |
| `src/edgar13f/server.py` | MCP stdio server on the low-level SDK 2.x `Server`; `python -m edgar13f.server`. |

## Data flow

```
MCP client ──stdio──> server.py ──> tools.call(name, args)
                                      │ validate.validate()           (§2, §6 argument reasons)
                                      │ source.filings(cik, as_of)    (EdgarSource | FixtureSource)
                                      │ rules.visible_filings()       (§3 filter; unknown_cik if empty)
                                      │ rules.resolve()               (§4 base + supplements, notice_only / not_yet_filed)
                                      │ source.rows(filing)           (info-table rows, already redacted)
                                      └ JSON envelope + DISCLAIMER → CallToolResult(text + structuredContent, isError=false)

EdgarSource.filings: sec_client.get(data.sec.gov/submissions/CIK##########.json [+ older pages])
                     → keep 13F-HR/HR-A/NT/NT-A → rules.visible → primary_doc.xml → parse.parse_cover
EdgarSource.rows:    sec_client.get(index.json) → info-table XML (store=False, never cached raw)
                     → parse.parse_infotable (blocklist first) → cache/rows/<accession>.json
```

## Where each contract rule is enforced and tested

| Rule | Enforced in | Tested in |
|---|---|---|
| §2 cik digits / leading zeros, dates, cusip array, unknown args → `invalid_argument` | `validate.validate` | `tests/unit/test_validate.py`, `tests/unit/test_server_stdio.py` |
| §2 quarter-end period, `period_b <= period_a` → `invalid_period` | `validate.validate` | `tests/unit/test_validate.py` |
| §2 `position_type` ≠ `"long"` → `unsupported_request` | `validate.validate` | `tests/unit/test_validate.py` |
| §2 cusip filter case-insensitive, citations unchanged | `tools._holdings`, `validate.validate` | `tests/unit/test_tools.py` |
| §3 visibility `filing_date <= as_of` | `rules.visible` (sole point), used by `rules.visible_filings`, `rules.resolve`, `EdgarSource.filings` | `tests/unit/test_rules.py`, `tests/invariants/test_leakage.py` (603 cases + mutant + no-op) |
| §4 ordering, base, supplements, UNSPECIFIED as RESTATEMENT | `rules.resolve`, `rules.kind` | `tests/unit/test_restatement.py` (exhaustive oracle + 5 planted mutants; synthetic §4 manager; 82 recorded cases vs data-set expectations; blocklist-in-restatement), `tests/unit/test_rules.py`, `tests/unit/test_tools.py`, leakage oracle in `tests/invariants/leakage.py` |
| §4 `notice_only` / `not_yet_filed` | `rules.resolve` | `tests/unit/test_rules.py`, `tests/unit/test_tools.py` |
| §5.1 JSON first text block, `structuredContent` identical, `isError=false` on declines | `server.result_for` | `tests/unit/test_server_stdio.py` |
| §5.1 disclaimer on every response | `tools._ok`, `tools._decline` | `tests/unit/test_validate.py`, `tests/unit/test_tools.py`, `tests/unit/test_server_stdio.py` |
| §5.2 filing record, sort, `edgar_url` | `rules.Filing.record`, `rules.visible_filings` | `tests/unit/test_rules.py`, `tests/unit/test_tools.py` |
| §5.3 rows as filed, not merged, no rescaling | `parse._row`, `tools._holdings` | `tests/unit/test_tools.py` |
| §5.4 consolidation, change types, earlier-period decline first | `tools._consolidate`, `tools.diff_holdings` | `tests/unit/test_tools.py` |
| §6 `unknown_cik` (never filed a 13F on or before `as_of`, or no such CIK) | `tools._visible_13f` | `tests/unit/test_tools.py` |
| Hard rule 2 blocklist | `parse._row` → `blocklist.is_blocked` | `tests/invariants/test_blocklist.py`, `tests/unit/test_restatement.py` (restatements, D2) |
| Hard rule 3 fair access | `sec_client.SecClient` | `tests/unit/test_sec_client.py` |
| Cache dir / unprivileged user | `config.cache_dir` | `tests/unit/test_config.py`, `tests/tools/unprivileged_probe.sh --offline` (CI step, with planted stray write) |

## Tests and checks

* `tests/unit/` – unit and end-to-end (stdio) tests, all offline (`tests/conftest.py` refuses sockets).
  `test_restatement.py` is the §4 hardening suite.
* `tests/invariants/leakage.py`, `test_leakage.py` – leakage suite and controls.
* `tests/invariants/test_blocklist.py` – synthetic-row blocklist proofs and fixture scan (recorded and synthetic).
* `tests/checks/` – size budget, MAP check, claims check; `tests/invariants/test_checks.py` plants a failure for each.
* `.github/workflows/invariants.yml` – the `invariants` job: the suites above, the checks, and the
  offline unprivileged-user probe with its planted-failure control.
* `tests/tools/` – not run in CI: fixture recorder, synthetic fixture writer, license audit, request
  stats, period consistency, unprivileged-user probe (live mode), SEC Form 13F Data Sets cross-check
  (`datasets_crosscheck.py`; data sets stay outside the repo), cold-cache latency (`cold_latency.py`).
* `tests/fixtures/<cik>/` – recorded, redacted EDGAR data (24 managers).
* `tests/fixtures/synthetic/9900000001/` – invented manager, one §4 case per period (benign rows only).
* `tests/fixtures/section4_expected.json` – expected §4 citations for recorded edge cases, derived from
  the SEC Form 13F Data Sets metadata.
