# edgar13f MCP tool contracts (frozen)

Version: 1.0 (2026-09-28). Machine-readable schemas: `contracts/tools.schema.json`.

This document is the complete interface the server under test must implement.
The evaluation harness (`evals/grade.py`) speaks MCP over stdio, calls the three
tools below with the arguments described here, and parses the results exactly as
described in section 5. Nothing outside this document is required or assumed.

## 1. Tools

| Tool | Purpose |
|---|---|
| `list_13f_filings(cik, as_of)` | Every Form 13F submission by the manager that was visible on `as_of`. |
| `get_holdings_as_of(cik, period, as_of[, cusip][, position_type])` | The manager's effective 13F holdings for one report period, as they could be known on `as_of`, plus the accession number(s) they come from. |
| `diff_holdings(cik, period_a, period_b, as_of[, cusip])` | Position-level differences between two report periods, each computed with the `get_holdings_as_of` rules on the same `as_of`. |

## 2. Common input conventions

* `cik` — string of 1–10 ASCII digits. Leading zeros are optional and ignored
  (`"1067983"` ≡ `"0001067983"`).
* `period`, `period_a`, `period_b` — ISO date `YYYY-MM-DD`. Must be a calendar
  quarter end (`03-31`, `06-30`, `09-30`, `12-31`); this is the Form 13F
  "report for the calendar year or quarter ended" date.
* `as_of` — ISO date `YYYY-MM-DD`. The knowledge date. See section 3.
* `cusip` (optional) — array of 1–50 nine-character CUSIPs. When present, the
  server MUST restrict returned holdings/changes to these CUSIPs and MUST NOT
  change anything else about the response (the same accession numbers are cited).
  CUSIP comparison is case-insensitive (filers occasionally enter lowercase
  letters); the server returns the CUSIP as filed. *(Clarified in PREREG Amendment 1.)*
* `position_type` (optional, `get_holdings_as_of` only) — enum with the single
  allowed value `"long"` (default). Form 13F contains no short positions
  (SEC Form 13F FAQ, Question 41). Any other value MUST be declined with
  `unsupported_request`.

Unknown argument names MUST be rejected with a decline (`invalid_argument`), not
silently ignored.

## 3. Point-in-time rule (normative)

A filing is visible on `as_of` **if and only if** its EDGAR filing date is on or
before `as_of`:

```
visible(filing, as_of)  :=  filing.filing_date <= as_of
```

The filing date is the EDGAR "Filing Date" (acceptance date, as EDGAR reports it
and as the SEC Form 13F Data Sets column `SUBMISSION.FILING_DATE` carries it).
Time of day is ignored: a filing dated `as_of` is visible on `as_of`; a filing
dated `as_of + 1 day` is not. The period of report and the signature date play no
role in visibility.

Nothing filed after `as_of` may influence any part of a response: not the
holdings rows, not the accession numbers cited, not the list of filings, not the
choice of which filing is the "latest". Returning or citing a filing with
`filing_date > as_of` is a **leakage violation**.

## 4. Amendment rule (normative)

SEC sources:

* Form 13F, Special Instruction 3 (https://www.sec.gov/files/form13f.pdf): "Amendments
  to a Form 13F report must either restate the Form 13F report in its entirety or
  include only holdings entries that are being reported in addition to those
  already reported in a current public Form 13F report for the same period. ...
  [the Manager must] check the appropriate box to indicate whether the amendment
  (a) is a restatement or (b) adds new holdings entries."
* SEC Division of Investment Management, *Frequently Asked Questions About Form 13F*,
  Questions 58b–58e (https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/frequently-asked-questions-about-form-13f):
  a restatement "resubmit[s] your entire filing, as corrected ... your amended
  filing will supersede your original filing" (58b); an amendment that adds new
  holdings "only should include the securities that are being added ... The
  amended filing will supplement the original filing" (58c); the EDGAR submission
  type for either kind is `13F-HR/A` (58e).

Given `cik`, `period`, `as_of`, let **V** be the set of visible (section 3)
submissions of type `13F-HR` or `13F-HR/A` filed by `cik` whose period of report
equals `period`. Order V by `(filing_date, amendment_no NULLS FIRST, accession_number)`
ascending. Classify each element of V as

* `ORIGINAL` — submission type `13F-HR`;
* `RESTATEMENT` — `13F-HR/A` whose cover-page amendment type is "RESTATEMENT";
* `NEW HOLDINGS` — `13F-HR/A` whose cover-page amendment type is "NEW HOLDINGS";
* `UNSPECIFIED` — `13F-HR/A` with no amendment type on the cover page. The
  evaluation never asks about a (cik, period) whose visible set contains an
  UNSPECIFIED amendment; the server MAY treat such an amendment as RESTATEMENT.

Then:

1. **base** = the last element of V (in the order above) whose kind is `ORIGINAL`
   or `RESTATEMENT`. A restatement supersedes the original and every amendment
   filed before it.
2. **supplements** = every `NEW HOLDINGS` element of V that sorts after **base**.
3. **effective holdings** = all information-table rows of **base**, plus all
   information-table rows of each supplement. Rows are returned as filed; the
   server MUST NOT merge, net, or de-duplicate rows (see §5.2 for the
   consolidation convention used by questions).
4. The response cites `accession_number` = **base** and
   `source_accessions` = [base] + supplements (in order).

If V is empty the request is declined (section 6): `notice_only` when a `13F-NT`
or `13F-NT/A` for the same (cik, period) is visible, `not_yet_filed` otherwise.

Combination reports (`13F COMBINATION REPORT`) and holdings reports covering other
included managers are treated like any other `13F-HR`: their information table is
the manager's information table.

If more than one `ORIGINAL` is visible for the same (cik, period), behaviour is
unspecified; the evaluation never asks about such a (cik, period).

## 5. Outputs

### 5.1 Envelope

Every tool result is an MCP `CallToolResult` whose **first `text` content block
is a JSON object** (UTF-8, no surrounding prose). Servers MAY additionally set
`structuredContent` to the same object; when both are present they must be
identical. `isError` MUST be `false` for both successful and declined responses;
`isError: true` is reserved for transport or internal failures and is scored as
an incorrect (non-)answer.

Every JSON object — success **and** decline — carries:

```json
"disclaimer": "13F reports long positions only; data may lag the period end by up to 45 days."
```

exactly that string. (Form 13F General Instruction: reports are due within 45 days
after the end of each calendar quarter; FAQ Q41: short positions are not reported.)

### 5.2 `list_13f_filings` success

```json
{
  "status": "ok",
  "disclaimer": "...",
  "cik": "1067983",
  "as_of": "2025-02-15",
  "filings": [
    {
      "accession_number": "0000950123-25-001234",
      "form_type": "13F-HR",                    // 13F-HR | 13F-HR/A | 13F-NT | 13F-NT/A
      "filing_date": "2025-02-14",
      "period_of_report": "2024-12-31",
      "is_amendment": false,
      "amendment_no": null,                     // integer or null
      "amendment_type": null,                   // "RESTATEMENT" | "NEW HOLDINGS" | null
      "report_type": "13F HOLDINGS REPORT",     // as on the cover page, or null
      "filing_manager_name": "BERKSHIRE HATHAWAY INC",
      "edgar_url": "https://www.sec.gov/Archives/edgar/data/1067983/000095012325001234/0000950123-25-001234-index.htm"
    }
  ]
}
```

`filings` contains every visible 13F submission (`13F-HR`, `13F-HR/A`, `13F-NT`,
`13F-NT/A`) of the manager, for any period, sorted by `(filing_date, accession_number)`
ascending. An empty array is a valid success when the CIK is a known 13F filer
but nothing is visible yet; `unknown_cik` is the decline for a CIK that has never
filed a Form 13F.

### 5.3 `get_holdings_as_of` success

```json
{
  "status": "ok",
  "disclaimer": "...",
  "cik": "1067983",
  "period": "2024-12-31",
  "as_of": "2025-02-15",
  "accession_number": "0000950123-25-001234",           // base filing (section 4)
  "source_accessions": ["0000950123-25-001234"],        // base + applied NEW HOLDINGS amendments
  "filing_date": "2025-02-14",                          // of the base filing
  "holdings": [
    {
      "accession_number": "0000950123-25-001234",       // the filing this row came from
      "name_of_issuer": "APPLE INC",
      "title_of_class": "COM",
      "cusip": "037833100",
      "figi": null,                                     // string or null
      "value": 75126000000,                             // integer, US dollars as filed
      "shares_or_principal_amount": 300000000,          // integer, as filed
      "sh_prn": "SH",                                   // "SH" | "PRN"
      "put_call": null,                                 // "PUT" | "CALL" | null
      "investment_discretion": "SOLE",                  // as filed
      "other_manager": null,                            // string or null, as filed
      "voting_authority_sole": 300000000,
      "voting_authority_shared": 0,
      "voting_authority_none": 0
    }
  ]
}
```

* `value` and `shares_or_principal_amount` are the integers **as filed** in the
  information table. Since 3 January 2023 Form 13F values are reported in whole
  US dollars (SEC Form 13F Data Sets readme, INFOTABLE.VALUE); the server MUST
  NOT rescale.
* One element per information-table row; rows for the same CUSIP are **not**
  merged. Questions that ask for a "total" for a CUSIP are graded by summing
  `shares_or_principal_amount` (and `value`) over all returned rows with that
  `cusip`, the same `put_call` and the same `sh_prn`. This is the
  **consolidation convention**.
* `holdings` order is not significant.

### 5.4 `diff_holdings` success

```json
{
  "status": "ok",
  "disclaimer": "...",
  "cik": "1067983",
  "period_a": "2024-09-30",
  "period_b": "2024-12-31",
  "as_of": "2025-02-15",
  "accession_a": "0000950123-24-011111",
  "accession_b": "0000950123-25-001234",
  "source_accessions_a": ["0000950123-24-011111"],
  "source_accessions_b": ["0000950123-25-001234"],
  "changes": [
    {
      "cusip": "037833100",
      "name_of_issuer": "APPLE INC",
      "put_call": null,
      "sh_prn": "SH",
      "shares_a": 400000000,
      "shares_b": 300000000,
      "shares_delta": -100000000,
      "value_a": 90000000000,
      "value_b": 75126000000,
      "value_delta": -14874000000,
      "change_type": "decreased"        // added | removed | increased | decreased | unchanged
    }
  ]
}
```

* Each period's effective holdings are computed with section 4 on the same
  `as_of`, then consolidated by key `(cusip, put_call, sh_prn)` (sums of shares
  and value). `changes` has one element per key present in either period.
* `added`: key absent in A, present in B. `removed`: present in A, absent in B.
  Otherwise `increased` / `decreased` / `unchanged` by the sign of `shares_delta`.
  Absent side: `shares_x = 0`, `value_x = 0`.
* `name_of_issuer` is any issuer name filed for that key (period B preferred).
* If either period would be declined by `get_holdings_as_of`, `diff_holdings`
  returns that decline (the earlier period's decline first if both).

## 6. Declines and errors

A decline is a normal (non-error) result:

```json
{
  "status": "declined",
  "disclaimer": "13F reports long positions only; data may lag the period end by up to 45 days.",
  "reason": "not_yet_filed",
  "message": "human-readable explanation (free text; not graded)"
}
```

`reason` codes (closed set; grading compares this string exactly):

| reason | when |
|---|---|
| `unknown_cik` | The CIK has never filed a Form 13F (`13F-HR`, `13F-HR/A`, `13F-NT`, `13F-NT/A`) on or before `as_of`, or does not exist. |
| `not_yet_filed` | The manager is a known 13F filer but no `13F-HR`/`13F-HR/A` for (cik, period) is visible on `as_of` (including any period that ends after `as_of`). |
| `notice_only` | Only `13F-NT`/`13F-NT/A` is visible for (cik, period): the holdings are reported by another manager. |
| `invalid_period` | `period` is not a calendar quarter-end date, or `period_b <= period_a`. |
| `invalid_argument` | Malformed `cik`/date/`cusip`, or an unknown argument name. |
| `unsupported_request` | The request asks for something Form 13F cannot contain (e.g. `position_type` other than `"long"`). |

Precedence when several apply: `invalid_argument` > `invalid_period` >
`unsupported_request` > `unknown_cik` > `notice_only` > `not_yet_filed`.

Transport-level errors (`isError: true`, or a non-JSON first text block) are
never a correct answer for any evaluation item.

## 7. What the evaluation checks (for information)

* **Exact match** of the expected value(s) — shares/value for a CUSIP (after the
  consolidation convention), accession number(s), filing metadata, decline reason.
* **Leakage**: any cited or returned accession with `filing_date > as_of`, or any
  holdings returned when nothing is visible.
* **Citation validity**: every accession number a response cites exists in
  EDGAR for that CIK, and the values reported for a CUSIP are exactly the values
  that accession's information table contains.
* **Decline correctness**: `status == "declined"` with the expected `reason`.
* The literal disclaimer string on every response.

The evaluation only asks about report periods 2024-03-31 through 2025-06-30 and
`as_of` dates no later than 2025-08-27.
