# Stage 6 report: packaging for PyPI and the MCP Registry

Labels: each claim is tagged with one of four upper-case labels (CLAUDE.md); untagged = assumed. Artifacts are in `reports/artifacts/`. Nothing was published and no PyPI or registry
login was made. Everything ran offline against recorded or synthetic fixtures (`SEC_USER_AGENT` unset): no
request was sent to sec.gov. Owner rulings S1-S3 (2026-10-18) and assumptions A41-A45 are in `REGISTER.md`.

## a. What changed

- Version 1.2.2 in `pyproject.toml`, `src/edgar13f/__init__.py`, both versions in `server.json` and
  `reports/artifacts/inspector_stage5.json` (the `inspector` job diffs against it).
- Console script `edgar13f-mcp` next to `edgar13f-server`, same function (P16, S1).
- `.github/workflows/publish.yml` (P14, S2): `release: published`; top-level `permissions: {}`; `build`
  (tag = `v` + pyproject version = both `server.json` versions, `python -m build`, `twine check`, artifact),
  `pypi` (environment `pypi`, `id-token: write`, trusted publishing, no token), `registry` (no environment,
  `id-token: write`, `contents: read`; `mcp-publisher` 1.8.1 with SHA-256 check, bounded wait for PyPI,
  `login github-oidc`, `publish`). Every action is pinned by commit SHA. No secrets.
- `PUBLISHING.md`: the deferred parts replaced by the owner checklist; sources and labels kept.
- `tests/unit/test_console_scripts.py`, `tests/tools/install_smoke.sh` (wheel mode), `tests/tools/license_audit.py`
  (extras).

## b. `src/` diff: only the version line
MEASURED: `git diff v1.2.1 -- src/` is one line, `__version__ = "1.2.1"` -> `"1.2.2"`; no gate applies, since answers cannot change (S3); see `reports/artifacts/src_diff_stage6.txt`.
MEASURED: the full suite passes offline (416 passed, 1 skipped: the root-only test; 414 + 2 new), the size, MAP and claims checks pass, and the Inspector check reproduces the committed artifact; see `reports/artifacts/pytest_stage6.txt`. The `invariants` and `inspector` CI jobs of the pull request are the authority for the merged commit.

## c. Entry point and package contents

- MEASURED: `uvx --from <wheel> edgar13f-mcp` starts and answers `initialize` (server `edgar13f` 1.2.2, protocol 2025-06-18); stage 5 recorded "An executable named `edgar13f-mcp` is not provided"; see `reports/artifacts/uvx_entrypoint_stage6.txt`.
- MEASURED: `install_smoke.sh` with `WHEEL=` runs the full handshake (four tools, malformed call `invalid_argument`, call without `SEC_USER_AGENT` is an error) through both `edgar13f-mcp` and `edgar13f-server`: SMOKE OK twice, 13 s with an empty uv cache; see `reports/artifacts/install_smoke_stage6.txt`.
- MEASURED: wheel 35,095 bytes (19 files), sdist 38,452 bytes (24 files); `twine check` passes on both; both hold only the package modules, the README, the licence and metadata: no test or fixture member and no `.json`, `.xml` or `.csv` file, so no holdings row; see `reports/artifacts/dist_contents_stage6.txt`.
- REASONED: redaction stays ON by default (no code under `src/` changed); the blocklist is untouched.

## d. Licence audit (rule 4)
MEASURED: `tests/tools/license_audit.py` now follows extras that a dependency requests (`pyjwt[crypto]` pulls in `cryptography`, `cffi`, `pycparser`, which the stage-5 run missed). On the installed 1.2.2 all 29 distributions are `ok` (MIT, BSD-3-Clause, Apache-2.0, PSF-2.0, MIT-0, `cryptography` Apache-2.0 OR BSD-3-Clause); no entry fails rule 4, so no DECISION NEEDED; see `reports/artifacts/license_audit.txt`. ASSUMED (A45): markers are evaluated for Linux and Python 3.11, so the Windows-only `pywin32` is not audited.

## e. Workflow checks

- MEASURED: actionlint 1.7.12 reports nothing on both workflow files (shellcheck was not installed, so embedded shell is not linted); see `reports/artifacts/actionlint_stage6.txt`.
- MEASURED: the tag-check script run locally accepts `v1.2.2` and rejects `v1.2.1` and `1.2.2`; the `mcp-publisher` 1.8.1 tarball downloaded on 2026-10-22 has the pinned SHA-256 (`reports/artifacts/server_json_validation_stage5.txt` records the same hash).
- Not run here: the workflow itself (it needs a published release, the `pypi` environment and PyPI).

## Not done / for the owner

Nothing is published. The owner checklist (PyPI 2FA account, pending publisher, `pypi` environment with reviewer
and tag rule `v*`, release `v1.2.2` from `main`, approval, verification) is in `PUBLISHING.md`. README.md is
unchanged by design. The workflow adds `id-token: write` (CI permissions) as ruled in S2.
