"""Normative rules: point-in-time visibility (CONTRACTS §3) and amendments (§4).

`visible` is the single enforcement point for §3. Every caller goes through
`rules.visible(...)` (module attribute lookup) so the leakage suite's mutant
control can disable it in one place.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

HOLDINGS_FORMS = ("13F-HR", "13F-HR/A")
NOTICE_FORMS = ("13F-NT", "13F-NT/A")
ALL_FORMS = HOLDINGS_FORMS + NOTICE_FORMS


@dataclass(frozen=True)
class Filing:
    cik: str
    accession_number: str
    form_type: str
    filing_date: str  # ISO YYYY-MM-DD (EDGAR filing date)
    period_of_report: str | None
    amendment_no: int | None = None
    amendment_type: str | None = None
    report_type: str | None = None
    filing_manager_name: str | None = None
    primary_doc: str | None = None

    @property
    def is_amendment(self) -> bool:
        return self.form_type.endswith("/A")

    @property
    def edgar_url(self) -> str:
        acc = self.accession_number
        return f"https://www.sec.gov/Archives/edgar/data/{self.cik}/{acc.replace('-', '')}/{acc}-index.htm"

    def record(self) -> dict:
        """The §5.2 filing record."""
        return {
            "accession_number": self.accession_number,
            "form_type": self.form_type,
            "filing_date": self.filing_date,
            "period_of_report": self.period_of_report,
            "is_amendment": self.is_amendment,
            "amendment_no": self.amendment_no,
            "amendment_type": self.amendment_type,
            "report_type": self.report_type,
            "filing_manager_name": self.filing_manager_name,
            "edgar_url": self.edgar_url,
        }

    def to_json(self) -> dict:
        return asdict(self)


def visible(filing: Filing, as_of: str) -> bool:
    """§3: visible iff EDGAR filing date <= as_of (ISO strings compare as dates)."""
    return filing.filing_date <= as_of


def visible_filings(filings: list[Filing], as_of: str) -> list[Filing]:
    out = [f for f in filings if visible(f, as_of)]
    return sorted(out, key=lambda f: (f.filing_date, f.accession_number))


def kind(filing: Filing) -> str:
    if filing.form_type == "13F-HR":
        return "ORIGINAL"
    if filing.amendment_type in ("RESTATEMENT", "NEW HOLDINGS"):
        return filing.amendment_type
    return "UNSPECIFIED"


def _order(f: Filing) -> tuple:
    return (f.filing_date, f.amendment_no is not None, f.amendment_no or 0, f.accession_number)


def resolve(filings: list[Filing], period: str, as_of: str) -> tuple[Filing, list[Filing]] | str:
    """§4: (base, supplements) for (period, as_of), or a decline reason.

    `filings` may include filings of any date; visibility is applied here.
    UNSPECIFIED amendments are treated as RESTATEMENT (permitted by §4).
    """
    vis = visible_filings(filings, as_of)
    v = sorted((f for f in vis if f.form_type in HOLDINGS_FORMS and f.period_of_report == period), key=_order)
    if not v:
        notice = any(f.form_type in NOTICE_FORMS and f.period_of_report == period for f in vis)
        return "notice_only" if notice else "not_yet_filed"
    base_idx = None
    for i, f in enumerate(v):
        if kind(f) in ("ORIGINAL", "RESTATEMENT", "UNSPECIFIED"):
            base_idx = i
    if base_idx is None:
        return "not_yet_filed"  # only NEW HOLDINGS amendments visible; see REGISTER.md
    supplements = [f for f in v[base_idx + 1:] if kind(f) == "NEW HOLDINGS"]
    return v[base_idx], supplements
