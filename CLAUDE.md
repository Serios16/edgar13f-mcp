HARD RULES (breaking any = stop and report)

1. contracts/ and PREREG_COMMITMENT.md are read-only. If the contract
   looks wrong or ambiguous, log DECISION NEEDED in REGISTER.md and
   stop work on that part. Never call add_repo or list_repos; work
   only in this repository.
2. Blocklist: before any other processing, redact every holdings row
   for gold ETFs/trusts, US energy sector ETFs, S&P 500 index
   funds/ETFs (e.g. IAU, XLE, VOO and equivalents) and UCITS copies.
   Match issuer-name patterns + CUSIPs, case-insensitive; over-dropping
   is fine, under-dropping is not. Never output, log, commit or display
   such rows, their values, or any price. Fixtures must not contain
   them. Prove it with synthetic-row tests.
   Switch (end users only): redaction is ON unless the environment
   variable EDGAR13F_REDACT is exactly "off". Default: ON. Never run
   the server with "off" against live SEC data or recorded fixtures,
   in any session or CI job; tests of "off" use synthetic rows only.
   The default list is never narrowed (ruling D2).
3. SEC fair access: User-Agent from $SEC_USER_AGENT; <= 5 req/s global;
   exponential backoff on 403/429 and on HTML error pages returned in
   place of data (treat as retryable); on-disk cache. If sec.gov is
   unreachable, stop and report; no mirrors or proxies.
4. Dependencies: permissive OSI licences (MIT/Apache/BSD/PSF/ISC) only. Do not depend on edgartools (it is
   the baseline). Do not copy AGPL code (e.g. sec-edgar-mcp).
5. MCP: official Python SDK 2.x, stdio only, no HTTP. Python 3.11.
6. No filer-specific logic: no hard-coded CIKs, accession numbers,
   dates or manager names in src/.
7. Push only your working branch; open a PR; never merge. Commit and
   push work in progress often.
8. No LLM API calls, no keys. No prices, charts or performance figures.
9. Scope: touch only src/edgar13f/, tests/, .github/workflows/,
   reports/, MAP.md, REGISTER.md, README.md, CLAUDE.md, pyproject.toml.
   Anything else goes to REGISTER.md as a proposal and is not done.

CLAIMS AND UNCERTAINTY
Label claims in reports: MEASURED (cite the command/CI run and artifact
path), REPORTED, REASONED, ASSUMED. Unlabelled = ASSUMED.
- Fact: settle it with a probe or test; MEASURED.
- Intent: take the most reversible option; log ASSUMED in REGISTER.md
  with trigger "stage gate"; continue.
- Scope: decline; log a proposal.
- Contracts, CI permissions, blocklist, new dependencies: stop and
  flag DECISION NEEDED in the PR.
