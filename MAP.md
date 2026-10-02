# MAP

## Modules (`src/edgar13f/`)

| Module | Role |
|---|---|
| `src/edgar13f/__init__.py` | Package version and the mandatory `DISCLAIMER` string (§5.1). |
| `src/edgar13f/config.py` | Cache dir resolution (`$EDGAR13F_CACHE_DIR` → `$XDG_CACHE_HOME/edgar13f` or `~/.cache/edgar13f` → per-user temp dir), `$SEC_USER_AGENT`, atomic JSON writes in the cache. |
| `src/edgar13f/sec_client.py` | Only code that talks to sec.gov: User-Agent, ≤5 req/s cross-process limiter, exponential backoff (403/429/5xx/network/truncated body (`IncompleteRead`, P7)/HTML-instead-of-data), on-disk cache, optional request headers (Range; 206 accepted, never cached), `requests.log`. |
| `src/edgar13f/blocklist.py` | Hard rule 2: issuer-name/title patterns + CUSIP list; `is_blocked()`; `redacting()` (ON unless `$EDGAR13F_REDACT` is exactly `off`). |
| `src/edgar13f/parse.py` | Cover-page parser and information-table parser; the blocklist is applied to each row before any other field is read (result memoised per table); `redact=False` only when `EdgarSource` passes the switch. |
| `src/edgar13f/rules.py` | `Filing` record, §3 `visible()` (single enforcement point), §4 `resolve()` (base + supplements), §5.2 filing record. |
| `src/edgar13f/sources.py` | `EdgarSource` (submissions JSON → filings, primary_doc.xml → cover, index.json + info table → redacted rows cached as JSON; with requested periods, only the pages and covers that can bear on them, REGISTER A17; rows parsed with redaction off cached apart in `rows-unredacted/`; `directory` = `managers.EdgarDirectory`) and `FixtureSource` (offline; `directory` = `FixtureDirectory`, names and 13F dates from the fixture filings). |
| `src/edgar13f/validate.py` | §2 input conventions and §6 decline precedence for argument-level reasons; Addendum A parameters (`issuer`, `max_positions`, `period` on `list_13f_filings`, `find_manager` arguments). |
| `src/edgar13f/narrow.py` | Addendum A1/A2/A5 after §4 and redaction: `issuer` filter (AND `cusip`), `matched_cusips`, `max_positions` ordering and cut (`total_positions`, `truncated`, `order`), agent mode (`$EDGAR13F_AGENT_MODE` exactly `on` → `max_positions=50`, `auto_limited`). |
| `src/edgar13f/managers.py` | Addendum A4 `find_manager`: ordering (13F filers first, then current name), `has_13f_filings` through `rules.visible`, blocklist on entity names; `EdgarDirectory` (EDGAR CIK lookup file for names, quarterly `full-index/form.gz` prefixes → earliest 13F date per CIK, submissions JSON for current names). |
| `src/edgar13f/tools.py` | The four tools (§1, §5, §6; A3, A4): envelopes, declines, consolidation for `diff_holdings`, `period` filter for `list_13f_filings`. |
| `src/edgar13f/schemas.py` | Tool input schemas advertised over MCP (inlined from `contracts/tools.schema.json`, plus Addendum A parameters and `find_manager`; descriptions per A6). |
| `src/edgar13f/server.py` | MCP stdio server on the low-level SDK 2.x `Server`; `python -m edgar13f.server` / `edgar13f-server`; refuses `EDGAR13F_REDACT=off` with a fixture dir. |

## Data flow

```
MCP client ──stdio──> server.py ──> tools.call(name, args)
                                      │ validate.validate()           (§2, §6 argument reasons)
                                      │ source.filings(cik, as_of, periods)  (EdgarSource | FixtureSource)
                                      │ rules.visible_filings()       (§3 filter; unknown_cik if empty)
                                      │ rules.resolve()               (§4 base + supplements, notice_only / not_yet_filed)
                                      │ source.rows(filing)           (info-table rows, already redacted)
                                      └ JSON envelope + DISCLAIMER → CallToolResult(text + structuredContent, isError=false)

EdgarSource.filings: sec_client.get(data.sec.gov/submissions/CIK##########.json [+ older pages])
                     → keep 13F-HR/HR-A/NT/NT-A → rules.visible → primary_doc.xml → parse.parse_cover
                     (periods given: only pages ending on/after the earliest period, more only while no
                      13F is visible; covers only for filings dated on/after it or indexed to a period asked)
EdgarSource.rows:    sec_client.get(index.json) → info-table XML (store=False, never cached raw)
                     → parse.parse_infotable (blocklist first) → cache/rows/<accession>.json
                       (EDGAR13F_REDACT=off: no blocklist, cache/rows-unredacted/<accession>.json)
get_holdings_as_of / diff_holdings rows → narrow.keep (cusip AND issuer) → narrow.holdings / narrow.changes
                     (max_positions or agent mode: order, cut, total_positions/truncated/order/auto_limited)
find_manager:        EdgarDirectory.search (cik-lookup-data.txt, daily) → first_13f (full-index/YYYY/QTRn/form.gz,
                     Range prefix, cache/f13index/<YYYY>Q<n>.json) → rules.visible(earliest 13F, as_of)
                     → heap by (no 13F, name) → current_name (submissions JSON) → blocklist on names
```

## Where each contract rule is enforced and tested

| Rule | Enforced in | Tested in |
|---|---|---|
| §2 cik digits / leading zeros, dates, cusip array, unknown args → `invalid_argument` | `validate.validate` | `tests/unit/test_validate.py`, `tests/unit/test_server_stdio.py` |
| §2 quarter-end period, `period_b <= period_a` → `invalid_period` | `validate.validate` | `tests/unit/test_validate.py` |
| §2 `position_type` ≠ `"long"` → `unsupported_request` | `validate.validate` | `tests/unit/test_validate.py` |
| §2 cusip filter case-insensitive, citations unchanged | `tools._holdings`, `validate.validate` | `tests/unit/test_tools.py` |
| §3 visibility `filing_date <= as_of` | `rules.visible` (sole point), used by `rules.visible_filings`, `rules.resolve`, `EdgarSource.filings` | `tests/unit/test_rules.py`, `tests/invariants/test_leakage.py` (981 cases, v1 tools + Addendum A parameters + `find_manager(as_of)`, mutant + no-op; the mutant must trip every category) |
| §4 ordering, base, supplements, UNSPECIFIED as RESTATEMENT | `rules.resolve`, `rules.kind` | `tests/unit/test_restatement.py` (exhaustive oracle + 5 planted mutants; synthetic §4 manager; 82 recorded cases vs data-set expectations; blocklist-in-restatement), `tests/unit/test_rules.py`, `tests/unit/test_tools.py`, leakage oracle in `tests/invariants/leakage.py` |
| §4 `notice_only` / `not_yet_filed` | `rules.resolve` | `tests/unit/test_rules.py`, `tests/unit/test_tools.py` |
| §5.1 JSON first text block, `structuredContent` identical, `isError=false` on declines | `server.result_for` | `tests/unit/test_server_stdio.py` |
| §5.1 disclaimer on every response | `tools._ok`, `tools._decline` | `tests/unit/test_validate.py`, `tests/unit/test_tools.py`, `tests/unit/test_server_stdio.py` |
| §5.2 filing record, sort, `edgar_url` | `rules.Filing.record`, `rules.visible_filings` | `tests/unit/test_rules.py`, `tests/unit/test_tools.py` |
| §5.3 rows as filed, not merged, no rescaling | `parse._row`, `tools._holdings` | `tests/unit/test_tools.py` |
| §5.4 consolidation, change types, earlier-period decline first | `tools._consolidate`, `tools.diff_holdings` | `tests/unit/test_tools.py` |
| §6 `unknown_cik` (never filed a 13F on or before `as_of`, or no such CIK) | `tools._visible_13f` | `tests/unit/test_tools.py` |
| Hard rule 2 blocklist | `parse._row` → `blocklist.is_blocked` | `tests/invariants/test_blocklist.py`, `tests/unit/test_restatement.py` (restatements, D2) |
| Hard rule 2 switch (`EDGAR13F_REDACT`) | `blocklist.redacting`, `EdgarSource.__init__`, `server.make_source` | `tests/invariants/test_blocklist.py` (switch section; synthetic rows only; truth table, separate cache, planted failures, no CI/test/tool sets it), `tests/unit/test_golden.py` (unset: byte-identical to v1.0.0 on every fixture) |
| Period-aware fetching (A17) | `EdgarSource.filings` | `tests/unit/test_lazy_fetch.py` (every fixture manager as an offline EDGAR, two page layouts, vs the v1.0.0 golden; unknown_cik paging; the documented limit) |
| A0 v1 calls byte-identical (agent mode unset) | `narrow` adds nothing without new parameters | `tests/unit/test_golden.py` (3,689 calls vs v1.0.0) |
| A1 `issuer` (substring, whitespace collapsed, AND `cusip`, `matched_cusips`) | `validate.fold`, `narrow.keep`, `narrow._matched` | `tests/unit/test_addendum.py` |
| A2 `max_positions` (groups by value / changes by abs delta, tie-breaks, never split) | `narrow.holdings`, `narrow.changes` | `tests/unit/test_addendum.py` |
| A3 `period` on `list_13f_filings` | `tools.list_13f_filings` (+ A17 lazy fetch) | `tests/unit/test_addendum.py`, `tests/unit/test_lazy_fetch.py` |
| A4 `find_manager` (ordering, `has_13f_filings` as of, declines, note) | `managers.find`, `managers.EdgarDirectory` | `tests/unit/test_find_manager.py`, `tests/invariants/test_leakage.py` (`find_manager(as_of)` cases) |
| A5 agent mode | `narrow.agent_mode`, `narrow._limit` | `tests/unit/test_addendum.py` |
| §3 for the new parameters and `find_manager(as_of)` | `rules.visible` (unchanged single point) | `tests/invariants/test_leakage.py` (mutant + no-op controls) |
| Hard rule 3 fair access | `sec_client.SecClient` | `tests/unit/test_sec_client.py` (incl. P7 truncated bodies, Range) |
| Cache dir / unprivileged user | `config.cache_dir` | `tests/unit/test_config.py`, `tests/tools/unprivileged_probe.sh --offline` (CI step, with planted stray write) |

## Tests and checks

* `tests/unit/` – unit and end-to-end (stdio) tests, all offline (`tests/conftest.py` refuses sockets and
  unsets `EDGAR13F_REDACT`). `test_restatement.py` is the §4 hardening suite; `test_golden.py` compares every
  fixture response with v1.0.0; `test_lazy_fetch.py` checks period-aware fetching; `test_parse.py` checks the
  row parser against the v1.0.0 parser.
* `tests/invariants/leakage.py`, `test_leakage.py` – leakage suite and controls.
* `tests/invariants/test_blocklist.py` – synthetic-row blocklist proofs and fixture scan (recorded and synthetic).
* `tests/invariants/test_blocklist.py` also holds the `EDGAR13F_REDACT` switch tests (synthetic rows only).
* `tests/golden/v1_0_fixture_responses.json` – hashes of every tool response over the fixtures, written by the
  v1.0.0 source (`tests/tools/fixture_golden.py`).
* `tests/checks/` – size budget, MAP check, claims check; `tests/invariants/test_checks.py` plants a failure for each.
* `.github/workflows/invariants.yml` – the `invariants` job: the suites above, the checks, and the
  offline unprivileged-user probe with its planted-failure control.
* `tests/tools/` – not run in CI: fixture recorder, synthetic fixture writer, license audit, request
  stats, period consistency, unprivileged-user probe (live mode), SEC Form 13F Data Sets cross-check
  (`datasets_crosscheck.py`; data sets stay outside the repo), cold-cache latency (`cold_latency.py`, also over
  stdio), v1.0 golden writer (`fixture_golden.py`), live v1.0.0-vs-new equivalence and the period-after-filing
  scan (`equivalence.py`), one-command install from GitHub (`install_smoke.sh`).
* `tests/fixtures/<cik>/` – recorded, redacted EDGAR data (24 managers).
* `tests/fixtures/synthetic/9900000001/` – invented manager, one §4 case per period (benign rows only).
* `tests/fixtures/section4_expected.json` – expected §4 citations for recorded edge cases, derived from
  the SEC Form 13F Data Sets metadata.
