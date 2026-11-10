---
name: edgar13f
description: Use for point-in-time questions about SEC Form 13F institutional holdings via the edgar13f MCP server - what a manager held at a quarter end, how it changed between quarters, which 13F filings and amendments existed on a date. Not for prices, performance, short positions or non-13F filings.
---

# SEC Form 13F holdings, point in time

Sources: `contracts/CONTRACTS.md`, `contracts/CONTRACTS_ADDENDUM_A.md` and `README.md` of the
edgar13f-mcp repository. Needs the `edgar13f` MCP server (stdio).

## Which tool

| Question | Tool |
|---|---|
| Only a manager's name is known | `find_manager(name, as_of)` -> CIK. Prefer candidates with `has_13f_filings: true`. `entity_name` is EDGAR's current name, not point-in-time. |
| Which 13F filings or amendments exist | `list_13f_filings(cik, as_of, period)` |
| What the manager held in one quarter | `get_holdings_as_of(cik, period, as_of)` |
| What changed between two quarters | `diff_holdings(cik, period_a, period_b, as_of)` |

## Always set the two dates

* `period`, `period_a`, `period_b`: the quarter-end date (`YYYY-03-31`, `-06-30`, `-09-30`, `-12-31`).
* `as_of`: the date the answer must have been knowable. A filing counts only if its EDGAR filing
  date is on or before `as_of`; nothing filed later influences the answer. Never default it to
  today when the question is about the past. Use the same `as_of` for both quarters of a diff.
* `cik` is 1-10 digits (leading zeros optional). Do not guess a CIK; resolve it with `find_manager`.

## Amendments and citations

* A restatement replaces the original and every earlier amendment. A new-holdings amendment adds
  rows. Rows are returned as filed (not merged, netted or rescaled; `value` is whole US dollars).
* `accession_number` is the base filing and `source_accessions` lists it plus applied
  new-holdings amendments; each row carries its own `accession_number`. Quote these when you
  state a number, with `filing_date`.
* For totals per security, sum rows with the same `cusip`, `put_call` and `sh_prn`.
  `diff_holdings` already does this and cites `accession_a`, `accession_b`.
* Answers change as amendments arrive: say which `as_of` the number is valid for.

## Large managers

* Narrow with `issuer` (case-insensitive name part, 2-100 characters), `cusip` (list of up to 50
  nine-character CUSIPs) or `max_positions` (1-200; largest positions by value, or largest
  changes by `|value_delta|` for a diff). Check `total_positions` and `truncated`.
* With `EDGAR13F_AGENT_MODE=on`, a call with none of `cusip`, `issuer`, `max_positions` is cut to
  50 positions and returns `auto_limited: true`. Say so; do not treat the list as complete.
  `matched_cusips` shows which securities an `issuer` filter matched.

## Declines

A decline is a normal result with `status: "declined"` and a `reason`; it is not an error.

| `reason` | Meaning | Next step |
|---|---|---|
| `unknown_cik` | The CIK has no 13F filing on or before `as_of`, or does not exist. | Re-check with `find_manager`; try a later `as_of`. |
| `not_yet_filed` | Known filer, but no holdings report for that period is visible on `as_of`. | Report that nothing was public yet; do not use a later `as_of` unless asked. |
| `notice_only` | Only a notice (13F-NT) is visible: another manager reports the holdings. | Say so; look at `list_13f_filings` for the notice. |
| `invalid_period` | `period` is not a quarter end, or `period_b` is not after `period_a`. | Fix the dates. |
| `invalid_argument` | Malformed `cik`, date, `cusip` or an unknown argument name. | Fix the call. |
| `unsupported_request` | Asks for what Form 13F cannot hold, e.g. `position_type` other than `long`. | Tell the user it is not available. |

Never turn a decline into a guessed answer.

## Limits

* Long positions only; no short positions. Data can lag the quarter end by up to 45 days, and
  amendments can come months later.
* No prices, charts or performance figures.
* Redaction is on by default: rows for gold ETFs/trusts, US energy-sector ETFs, S&P 500 index
  funds/ETFs and UCITS copies are removed, with some over-matching (e.g. "SPDR S&P" funds). A
  removed CUSIP returns `ok` with no rows, so absence of a row is not proof of no holding. Only
  the server's operator can change this, with `EDGAR13F_REDACT=off`; do not ask for it.
* Every response carries the disclaimer; keep its meaning when you answer.

## Not advice

Report what was filed. Do not present results as investment advice or a recommendation.
