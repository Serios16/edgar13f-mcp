# Publishing (owner checklist; nothing has been published)

Nothing is published yet. Every step below needs the owner's PyPI and GitHub accounts. Labels as in
`reports/`: REPORTED = from the sources at the end (read 2026-10-15), MEASURED = run here with the
artifact named, REASONED = inferred.

## 0. State

- Done (rulings, 2026-10-15 and 2026-10-18): the distribution is `edgar13f-mcp` 1.2.2; the import package
  (`edgar13f`) and the command `edgar13f-server` are unchanged; the console script `edgar13f-mcp` (P16) is
  added next to it, both pointing to `edgar13f.server:main`.
- MEASURED: `uvx --from <wheel> edgar13f-mcp` starts and answers `initialize`; stage 5 recorded the failure
  (`reports/artifacts/uvx_entrypoint_stage6.txt`, `reports/artifacts/install_smoke_stage6.txt`).
- MEASURED: the name `edgar13f` is taken on PyPI by an unrelated project (Edgar13F 0.2.0, a 13F scraper
  uploaded 2023-08-26); `edgar13f-mcp` was free on 2026-10-15
  (`reports/artifacts/server_json_validation_stage5.txt`).
- REPORTED: a pending trusted publisher does not reserve a name; another upload can take it first [4]. Do
  steps 2 to 4 below without long gaps.
- MEASURED: the wheel (35 KB) and the sdist (38 KB) hold only `src/edgar13f/`, the README, the licence and
  metadata: no tests, fixtures or data (`reports/artifacts/dist_contents_stage6.txt`).
- Release workflow `.github/workflows/publish.yml` (P14 un-deferred): see section 1.

## 1. Owner checklist (in this order)

1. **PyPI account with 2FA.** Create or use an account on pypi.org and enable 2FA.
2. **Pending publisher** (REPORTED [4]): pypi.org → Account → Publishing → add a pending GitHub publisher:
   PyPI project name `edgar13f-mcp`, owner `Serios16`, repository `edgar13f-mcp`, workflow file name
   `publish.yml`, environment `pypi`.
3. **GitHub environment `pypi`** (REPORTED [3]): repository Settings → Environments → New environment `pypi`;
   required reviewers: `Serios16` (leave "Prevent self-review" off, since the owner is the only reviewer);
   under deployment branches and tags add a tag rule `v*`.
4. **Merge the stage-6 pull request**, then publish the release `v1.2.2` from `main`: Releases → Draft a new
   release → create the tag `v1.2.2` on `main` → Publish release. The `build` job fails unless the tag equals
   `v` + the `pyproject.toml` version + both `server.json` versions.
5. **Approve** the `pypi` environment deployment when the workflow run asks for it (Actions → publish). Only
   after that does the `pypi` job upload; the `registry` job then waits (at most 10 minutes) until PyPI serves
   the version and publishes `server.json` to the MCP Registry.
6. **Verify**:
   - `SEC_USER_AGENT="Your Name your.email@example.com" uvx edgar13f-mcp` starts a stdio server (stop it with Ctrl-D);
   - `curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.Serios16/edgar13f-mcp"`
     lists version 1.2.2.

If only the `registry` job fails after PyPI succeeded (the registry is in preview [1]), re-run the failed job
from the Actions page; PyPI does not accept the same version twice, so never re-run `pypi` for a version that is
already up. A fix needs a new version and a new release.

### What `publish.yml` does

REASONED from the file; `reports/artifacts/actionlint_stage6.txt` shows it lints clean.

- Trigger `release: published`; top-level `permissions: {}`; no secrets; every action pinned by commit SHA.
- `build` (`contents: read`): tag check, `python -m build`, `twine check`, uploads `dist/` as an artifact.
- `pypi` (`environment: pypi`, `id-token: write`): downloads `dist/` and publishes with
  `pypa/gh-action-pypi-publish` (trusted publishing, no token) [5].
- `registry` (`id-token: write`, `contents: read`, no environment): installs `mcp-publisher` 1.8.1 and checks its
  SHA-256, waits for PyPI, then `mcp-publisher login github-oidc` and `mcp-publisher publish` [3].

## 2. Ownership marker for the MCP Registry

REPORTED [2]: for PyPI packages the registry looks for `mcp-name: <server name>` in the package
README (the PyPI description), may be in an HTML comment, followed by whitespace, a tag or `-->`.
Done: the first lines of `README.md` carry `<!-- mcp-name: io.github.Serios16/edgar13f-mcp -->`,
and `pyproject.toml` uses `README.md` as the description. `tests/unit/test_server_json.py` keeps the
marker, `server.json` name, versions and description length in step.

## 3. server.json

- REPORTED [1][6]: schema `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json`
  (latest released; a draft adds cargo and URL-template changes); required `name`, `description`
  (at most 100 characters), `version`; `name` is reverse-DNS with one slash. Supported package types:
  npm, pypi, nuget, cargo (draft), oci, mcpb [2]. Official registry: PyPI only from
  `https://pypi.org`; only `_meta` under `io.modelcontextprotocol.registry/publisher-provided` is kept [6].
- MEASURED: `server.json` passes the 2025-12-11 schema (jsonschema, Draft 7) and
  `mcp-publisher validate` (1.8.1); a 101-character description is rejected
  (`reports/artifacts/server_json_validation_stage5.txt`).
- MEASURED: `validate` also accepted `registryBaseUrl: https://pypi.example.org`, so it checks the
  schema, not ownership or the official-registry rules; a real check happens only at `publish`
  (`reports/artifacts/server_json_validation_stage5.txt`).
- Not advertised: `EDGAR13F_REDACT` (the redaction switch stays an end-user setting, default ON) and
  `EDGAR13F_FIXTURE_DIR` (test hook).
- Bump `version` and `packages[0].version` with every release: `tests/unit/test_server_json.py` fails otherwise, and the
  `build` job of `publish.yml` refuses a release whose tag differs from either.

## 4. The MCP Registry

REPORTED [1][3]: the workflow's `registry` job runs `mcp-publisher login github-oidc` and
`mcp-publisher publish`, which needs `permissions: id-token: write` [3]. By hand (not needed when the
workflow is used):

```sh
mcp-publisher login github        # device flow; grants io.github.<your-login>/*
mcp-publisher publish             # reads ./server.json
```

The registry is in preview: breaking changes or data resets may occur [1].

ASSUMED: the namespace is written `io.github.Serios16` as in the repository URL. If `publish` answers
"You do not have permission to publish this server", use the exact login spelling that
`mcp-publisher login github` grants, and change it in both `server.json` and the README marker.

## Sources (REPORTED, read 2026-10-15)

1. MCP Registry quickstart: https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/quickstart.mdx
2. Package types and ownership verification: https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/package-types.mdx
3. Authentication and GitHub Actions: https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/authentication.mdx, https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/github-actions.mdx
4. PyPI, creating a project with a trusted publisher: https://github.com/pypi/warehouse/blob/main/docs/user/trusted-publishers/creating-a-project-through-oidc.md (docs.pypi.org did not resolve from this environment)
5. PyPI, publishing with a trusted publisher: https://github.com/pypi/warehouse/blob/main/docs/user/trusted-publishers/using-a-publisher.md
6. server.json format, changelog and official-registry requirements: https://github.com/modelcontextprotocol/registry/tree/main/docs/reference/server-json
