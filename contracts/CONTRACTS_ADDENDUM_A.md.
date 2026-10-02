# Addendum A: agent-use extensions (additive)

Version A.1 (2026-10-02). Extends CONTRACTS.md v1.0. Nothing here changes v1 behaviour.

## A0. Compatibility (normative)
- Any call that uses none of the parameters or tools introduced below MUST return a
  response byte-identical to v1.1.0 (isError + first text block), with `EDGAR13F_AGENT_MODE`
  unset.
- §3 (point-in-time) and §4 (amendments) apply unchanged. The new parameters only filter or
  order rows after §4 resolution. They never change `accession_number`,
  `source_accessions` or `filing_date` (same rule as the `cusip` filter in §2).
- Redaction (CLAUDE.md rule 2) is applied before any filter.

## A1. `issuer` (get_holdings_as_of, diff_holdings)
- Optional string, 2-100 characters. A case-insensitive substring match against
  `name_of_issuer` as filed, with runs of whitespace collapsed to one space.
- Combined with `cusip` as AND.
- When present, the response adds `matched_cusips`: the sorted distinct CUSIPs (as filed)
  that matched.

## A2. `max_positions` (get_holdings_as_of, diff_holdings)
- Optional integer, 1-200.
- get_holdings_as_of: rows are grouped by the consolidation key (cusip, put_call, sh_prn).
  Groups are ordered by summed `value` descending, then cusip ascending, put_call (null
  first), sh_prn. The first `max_positions` groups are returned with all their rows as filed.
  A group is never split.
- diff_holdings: `changes` are ordered by |value_delta| descending, then the same tie-breaks,
  and cut to `max_positions`.
- When present, the response adds `total_positions` (count after all filters, before
  the cut), `truncated` (bool) and `order` ("value_desc" or "abs_value_delta_desc").

## A3. `period` (list_13f_filings)
- Optional quarter-end date. Only filings whose `period_of_report` equals it are listed.
  Sorting and visibility follow §5.2 and §3.

## A4. New tool `find_manager(name[, as_of][, limit])`
- `name`: 3-100 characters, a case-insensitive substring of EDGAR entity names.
  `limit`: 1-20, default 10.
- Returns `{"status":"ok","disclaimer":...,"query":...,"candidates":[{"cik","entity_name",
  "has_13f_filings"}],"note":...}`.
- Candidates with `has_13f_filings: true` come first, then by name.
- `entity_name` is EDGAR's current name, so this tool is not point-in-time for names.
- If `as_of` is given, `has_13f_filings` is true only if a 13F-HR, 13F-HR/A, 13F-NT or
  13F-NT/A dated on or before `as_of` exists.
- `note` states both points.
- Declines follow §6 (`invalid_argument` for bad lengths, dates or unknown argument names).
  The disclaimer is required.

## A5. Agent mode (`EDGAR13F_AGENT_MODE`)
- Off unless exactly "on".
- When on, a get_holdings_as_of or diff_holdings call that has none of `cusip`, `issuer`
  or `max_positions` is answered as if `max_positions=50`, and the response adds
  `auto_limited: true`.
- When off or unset, there is no effect.

## A6. Tool descriptions
- The MCP tool descriptions SHOULD tell models to resolve names with `find_manager`, to
  narrow with `issuer`/`cusip`/`max_positions`, and that `as_of` means what was publicly
  filed by that date. They are not graded.
