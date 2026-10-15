# Stage 5 report: protocol checks and registry readiness

Labels: each claim is tagged measured, reported, reasoned or assumed (upper-case tag on the line);
untagged = assumed. Artifacts are in `reports/artifacts/`. Everything in this stage ran offline
against recorded or synthetic fixtures (`SEC_USER_AGENT` unset): no request was sent to sec.gov.
The acceptance criteria were fixed by the brief before any work.

REPORTED (evaluator, aggregates only): gate 4 PASS on f7ee806, tagged v1.2.0, identical to gates 1-3.
LLM-in-the-loop eval: edgar13f 160/160, EdgarTools 105/160.

`src/` changed once, under ruling R2: fix F18 (section b), test first, +26 lines in `config.py` and
`sources.py` (1,450 lines in total, none over 250). The v1.2.1 gate therefore applies: tag v1.2.1 only if
gate 5 on the merged commit passes every primary gate with generated >= 698/700 and 0 leaks.
MEASURED: the full suite passes offline (414 passed, 1 skipped: the root-only test); see `reports/artifacts/pytest_stage5.txt`.

## a. Inspector CLI check (`inspector` CI job)

Read first: the Inspector's README, CLI README and "Smoke-testing an MCP server" guide (v2 line). The
check follows its syntax: `mcp-inspector --cli <command> -- <inspector options>`, `--method
initialize | tools/list | tools/call`, `--tool-args-json`, `--format json`, a bounded
`--connect-timeout`, exit codes captured before `jq`, and an isolated token/secret store
(`MCP_STORAGE_DIR`, `MCP_INSPECTOR_OAUTH_STATE_PATH`, `MCP_INSPECTOR_SECRET_STORE=memory`).

- Tooling (R1): `actions/setup-node@v4` and `@modelcontextprotocol/inspector@2.11.0` (exact; transitive
  packages locked in `tests/inspector/package-lock.json`, `npm ci --ignore-scripts`). Licence: Apache-2.0,
  with MIT for contributions not yet relicensed (the package's LICENSE file). Node >= 22.19 required.
- `tests/inspector/inspector_check.sh` starts `python -m edgar13f.server` with
  `EDGAR13F_FIXTURE_DIR` and `SEC_USER_AGENT` unset and asserts, in each protocol era: connection; exactly
  the four tools; one call per tool with the disclaimer (in `structuredContent` and the first text block,
  which must be the same object), `isError: false`, status ok; a malformed call (numeric `cik`) returns
  the `invalid_argument` decline with `isError: false`; and no `requests.log` in the cache dir.
- MEASURED: all assertions pass in both eras, on MCP SDK 2.2.0 and 2.3.0 (same summary); see `reports/artifacts/inspector_stage5.json`.
- MEASURED: CI run 60 (https://github.com/Serios16/edgar13f-mcp/actions/runs/38770341562, job `inspector`) passed every step on SDK 2.3.0, and its summary equals `reports/artifacts/inspector_stage5.json` (the job diffs them).
- MEASURED: planted failure: the same check against `tests/inspector/three_tools_server.py` (the real server without `find_manager` in tools/list) exits 1 at "tools/list returned [3 names], expected exactly [4]"; CI run 60 confirms; see `reports/artifacts/inspector_planted_stage5.txt`.

Negotiated protocol version (finding F13):

- MEASURED: legacy era (the Inspector's default): `initialize` → `2025-11-25`. Modern era: `2026-07-28`, with no `initialize` on the wire: the Inspector sends server/discover (the server answers `supportedVersions: ["2026-07-28"]`) and then each request carries the version in `_meta`; same on SDK 2.2.0 and 2.3.0; see `reports/artifacts/protocol_tap_stage5.jsonl` (envelopes only, recorded by `tests/tools/stdio_tap.py`).
- No protocol-version mismatch: the Inspector connects in both eras and every tool works. REASONED:
  the SDK 2.x low-level `Server` serves both eras over stdio, so a 2026-07-28 client and a 2025-11-25
  client both reach the same `on_list_tools`/`on_call_tool` handlers. Nothing in `src/` or the SDK was changed.
- MEASURED: CI now resolves `mcp>=2.0,<3` to SDK 2.3.0 (stage 4 measured 2.2.0); the CI run 60 wire tap reports `mcp 2.3.0`; the local check on both versions is in `reports/artifacts/protocol_tap_stage5.jsonl` (A38).

## b. Lifecycle tests (`tests/invariants/test_lifecycle.py`, new step in the `invariants` job)

The mid-call tests run `tests/invariants/lifecycle_server.py`: the real stdio loop, `EdgarSource`,
`SecClient` (rate limiter, atomic writes, cache) and an offline opener over the synthetic manager
(benign rows only; sockets refused) that holds the second information table in flight, after the first
table's rows were cached. Each check is a function returning its problems; each runs on the real
server and on a planted defect.

| Check | Real server | Planted control (must be caught) |
|---|---|---|
| Close stdin → exit within 10 s, code 0 | exit 0 after 0.265 s (fixture and offline-EDGAR servers) | server keeps running after stdin EOF → "still running" |
| Malformed JSON-RPC line → error or ignored; still answers | 6 lines, all ignored (no reply), `tools/list` and `tools/call` correct after each | stdin filter exits on a non-JSON line → "server exited" |
| SIGTERM mid-call | client: `MCPError` (Connection closed) 0.006 s after the signal; cache whole; fresh start correct, reusing the cache | server ignores SIGTERM → no client error within the limit |
| SIGKILL mid-call | client: `MCPError` 0.011 s after the signal; cache whole; fresh start correct | non-atomic rows write killed halfway → "rows file is not whole JSON" and fresh start returns an error |

"Cache whole" means: every HTTP cache entry byte-identical to what was served, every rows file equal to
the parsed table, every `requests.log` line a whole record, no temporary file, nothing else in the dir.

- MEASURED: the table above, on the fixed code; see `reports/artifacts/lifecycle_stage5.json` (from `python -m tests.tools.lifecycle_observe`, SDK 2.3.0).
- MEASURED: the 12 lifecycle tests (11 + the F18 test below) pass locally; the first 11 also in CI run 60 (step "Lifecycle tests", 46 s); see `reports/artifacts/pytest_stage5.txt`.
Random-moment probe (`tests/tools/kill_fuzz.py`): 200 runs, SIGKILL and SIGTERM alternating, the signal
after a uniform delay within the call (about 4 s), every information table repeated 4,000 times so that
cache writes are large; after each kill the cache check and a fresh start.

- MEASURED (F18, on src = v1.2.0): 2 of 200 runs left a temporary file in the cache (a rows file name with `.tmp<pid>-<thread>`, once after SIGTERM, once after SIGKILL); no file the server reads was partial or corrupt, and every fresh start answered correctly; see `reports/artifacts/kill_fuzz_v1.2.0.json`.
- Cause: `config.write_json` (and `SecClient.get`) write a temporary name and rename it; a kill between
  the two leaves the temporary file, which nothing reads or removes (up to the size of a rows file,
  tens of MB for a large filer), against "the cache holds no partial files".
- Fix (R2, test first): `config.sweep_stale_temp`, called when `EdgarSource` starts, removes temporary
  files whose writer process is dead and keeps those of live processes (another server may share the cache).
- MEASURED: `test_fresh_start_removes_temp_files_of_dead_processes_only` failed on v1.2.0 and passes with the fix; see `reports/artifacts/tempfile_fix_stage5.txt`.
- MEASURED: with the fix, the same probe (200 runs, same seed, now also checking the cache after the fresh start): one kill left a temporary file, gone after the fresh start in every run; 0 partial or corrupt files the server reads, 0 wrong fresh-start answers; see `reports/artifacts/kill_fuzz_fixed.json`.
- ASSUMED (A39): a temporary file may exist between a kill and the next start; removing it before that
  would need another write scheme (e.g. Linux `O_TMPFILE`).
- MEASURED (F14, not a defect under the brief): the SDK's stdio server ignores malformed lines without a JSON-RPC `-32700` reply, so a client that sent one waits for its timeout; see `reports/artifacts/lifecycle_stage5.json`. Proposal P15 (upstream note only).

## c. Registry readiness (no publishing)

Sources and steps: `PUBLISHING.md` (REPORTED, read 2026-10-15 from the registry's and PyPI's docs).

- REPORTED: current released schema `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`; package types npm, pypi, nuget, oci, mcpb (cargo in the draft); PyPI ownership = `mcp-name: <server name>` in the package README; the official registry accepts PyPI only from `https://pypi.org`; GitHub namespace `io.github.<login>/*`; the registry is in preview.
- `server.json`: `io.github.Serios16/edgar13f-mcp`, version 1.2.0, PyPI package `edgar13f-mcp`,
  `runtimeHint: uvx`, stdio, variables `SEC_USER_AGENT` (required), `EDGAR13F_AGENT_MODE`,
  `EDGAR13F_CACHE_DIR` (A37). README carries `<!-- mcp-name: io.github.Serios16/edgar13f-mcp -->`.
- MEASURED: valid against the 2025-12-11 schema (jsonschema 4.26.0, Draft 7) and with `mcp-publisher validate` 1.8.1; the planted 101-character description is rejected by both; see `reports/artifacts/server_json_validation_stage5.txt`.
- MEASURED (F15): `mcp-publisher validate` also accepted `registryBaseUrl: https://pypi.example.org`: it checks the schema, not ownership or the official-registry rules, which only `publish` applies; see `reports/artifacts/server_json_validation_stage5.txt`.
- MEASURED (F16): the PyPI name `edgar13f` is taken by an unrelated project (Edgar13F 0.2.0, 2023); `edgar13f-mcp` was free; see `reports/artifacts/server_json_validation_stage5.txt`. The rename is outside R3 (`pyproject.toml`): proposal P13, owner decision.
- `tests/unit/test_server_json.py` keeps `server.json` in step with the package (name pattern, README
  marker, description <= 100, one version in `server.json`, `pyproject.toml` and `__version__`, PyPI over
  stdio, an allowlist of advertised variables) with planted inconsistencies.

## d. README, MAP, REGISTER

README: registry marker (HTML comment) and a short "Protocol checks" note in the Tests section pointing to
the `inspector` job, its script and `reports/artifacts/inspector_stage5.json`. MAP: three rows in the
rule table (protocol, lifecycle, registry metadata) and the new test files. REGISTER: gate 4 and the
v1.2.1 condition, rulings R1-R3, ASSUMED A32-A38, proposals P13-P15.
MEASURED: size budget, MAP and claims checks pass (`src/` 1,450 lines); part of `reports/artifacts/pytest_stage5.txt`.

## Findings

| # | Finding | Action |
|---|---|---|
| F13 | No protocol mismatch: SDK 2.2.0/2.3.0 serve both 2025-11-25 (`initialize`) and 2026-07-28 (`server/discover`, no handshake) over stdio. | Both eras checked in CI on every push. |
| F14 | Malformed JSON-RPC lines get no reply (ignored, not a `-32700` error). | Within the brief; P15. |
| F15 | `mcp-publisher validate` does not check ownership or registry base URLs. | Documented in `PUBLISHING.md`. |
| F16 | PyPI name `edgar13f` is taken by another project. | P13: owner to rename the distribution (proposed `edgar13f-mcp`). |
| F18 | A kill between a cache write and its rename left a temporary file in the cache for good (2 of 200 random kills). | Fixed under R2, test first: stale temporary files of dead processes are removed at start. v1.2.1 gate applies. |
| F17 | CI resolves MCP SDK 2.3.0 (stage 4: 2.2.0); the inspector job pins the negotiated versions, so an SDK release that changes them turns CI red. | A33, A38. |

## Not done

- No publishing, no PyPI or registry login, no release workflow with `id-token: write` (P14: CI
  permission, owner's decision). No change to `pyproject.toml` or the SDK; `src/` only for F18.
- Version strings stay 1.2.0 (`pyproject.toml` is outside R3). If gate 5 passes and v1.2.1 is tagged,
  `pyproject.toml`, `__version__` and both versions in `server.json` move together
  (`tests/unit/test_server_json.py` fails otherwise).
