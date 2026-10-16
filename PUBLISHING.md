# Publishing (owner only; not done)

Nothing has been published. Every step below needs the owner's PyPI and GitHub accounts. Labels as in
`reports/`: REPORTED = from the sources at the end (read 2026-10-15), MEASURED = run here with the
artifact named, REASONED = inferred.

## 0. PyPI name (done) and the command clients run (open)

- MEASURED: the name `edgar13f` is taken on PyPI by an unrelated project (Edgar13F 0.2.0, a 13F scraper
  uploaded 2023-08-26); `edgar13f-mcp` was free on 2026-10-15
  (`reports/artifacts/server_json_validation_stage5.txt`).
- Done (ruling, 2026-10-15): the distribution is `edgar13f-mcp` 1.2.1; the import package (`edgar13f`),
  `python -m edgar13f.server` and the command `edgar13f-server` are unchanged. `install_smoke.sh`:
  SMOKE OK (`reports/artifacts/install_smoke_stage5.txt`).
- REPORTED: a pending trusted publisher does not reserve a name; another upload can take it first [4].
- Open (REGISTER P16), MEASURED: `uvx edgar13f-mcp`, which registry clients run for
  `runtimeHint: "uvx"`, fails because the package provides only `edgar13f-server`
  (`reports/artifacts/uvx_entrypoint_stage5.txt`). Before publishing, either add a console script
  `edgar13f-mcp = "edgar13f.server:main"` next to `edgar13f-server`, or change `server.json` so that
  clients start `edgar13f-server`.

## 1. PyPI with trusted publishing (no API token)

REPORTED [4][5]:

1. On pypi.org (account with 2FA): Account → Publishing → add a *pending* GitHub publisher with
   PyPI project name `edgar13f-mcp`, owner `Serios16`, repository `edgar13f-mcp`, workflow file
   name (e.g. `publish.yml`) and environment `pypi` (optional, strongly recommended).
2. In GitHub: create the environment `pypi` (Settings → Environments), restricted to release tags,
   ideally with a required reviewer [3].
3. A workflow triggered by a `v*` tag, job-level `permissions: id-token: write`, `environment: pypi`:
   build the sdist and wheel (e.g. `python -m pip install build && python -m build`), then
   `uses: pypa/gh-action-pypi-publish@release/v1` with no username or password. The first run creates
   the project; the pending publisher becomes a normal one.

Deferred by ruling (REGISTER P14): no release workflow and no `id-token` permission until the owner
decides to publish.

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
- Bump `version` and `packages[0].version` with every release (the test fails otherwise).

## 4. Publish to the MCP Registry (after the PyPI release exists)

REPORTED [1][3]:

```sh
# install mcp-publisher (binary from the registry's GitHub releases, or `brew install mcp-publisher`)
mcp-publisher login github        # device flow; grants io.github.<your-login>/*
mcp-publisher publish             # reads ./server.json
curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.Serios16/edgar13f-mcp"
```

Or in the release workflow: `permissions: id-token: write`, then `mcp-publisher login github-oidc` and
`mcp-publisher publish` [3]. The registry is in preview: breaking changes or data resets may occur [1].

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
