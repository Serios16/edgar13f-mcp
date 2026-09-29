"""Holdings blocklist (hard rule 2).

Redacts every information-table row that is (or could be) a gold ETF/trust, a
US energy-sector ETF, an S&P 500 index fund/ETF, or a UCITS copy of any of
them. Matching is case-insensitive over issuer name + title of class, plus a
CUSIP list. Over-dropping is acceptable; under-dropping is not. Applied by
`parse.parse_infotable` to each row before any other field is read, so a
blocked row never reaches the cache, a response, a log or a fixture.
"""

from __future__ import annotations

import re

_ETF_WORDS = (
    r"(ETF|ETN|ETC|FUND|FD|FDS|TRUST|TR|SHS|SHARES|MINISHARES|INDEX|IDX|SPDR|SELECT\s*SECTOR"
    r"|ISHARES|VANGUARD|INVESCO|PROSHARES|DIREXION|ALPHADEX|FIDELITY|SCHWAB|VANECK|X-?TRACKERS"
    r"|ULTRA|BULL|BEAR|PORTFOLIO|UNIT|UNITS|SBI|SECTOR|BULLION|PHYSICAL)"
)

_PATTERNS = [
    # S&P 500 index funds/ETFs and anything naming the index (incl. leveraged/inverse).
    r"S\s*&\s*P\s*-?\s*500",
    r"\bS\s*AND\s*P\s*-?\s*500",
    r"\bSP\s*-?\s*500",
    r"\bSPX\b",
    r"\b500\b.*" + _ETF_WORDS + r"\b",
    r"\b" + _ETF_WORDS + r"\b.*\b500\b",
    r"\bSPDR\s+S\s*&?\s*P\b",
    r"\bSPDR\s+(TR|TRUST)\b.*\bUNIT\b",
    # Gold ETFs / trusts / ETCs.
    r"\bGOLD\b.*\b" + _ETF_WORDS + r"\b",
    r"\b" + _ETF_WORDS + r"\b.*\bGOLD\b",
    r"\bGLD\b",
    r"\bIAU[M]?\b",
    r"\bBULLION\b",
    # US energy-sector ETFs (energy, oil & gas, oil services, E&P).
    r"\bENERGY\b.*\b" + _ETF_WORDS + r"\b",
    r"\b" + _ETF_WORDS + r"\b.*\bENERGY\b",
    r"\bOIL\b.*\b" + _ETF_WORDS + r"\b",
    r"\b" + _ETF_WORDS + r"\b.*\bOIL\b",
    r"\bOIL\s*&?\s*GAS\b",
    r"\bOILGAS\b",
    r"\bXLE\b",
    r"\bXOP\b",
    r"\bVDE\b",
    r"\bMLP\b",
    r"\bALERIAN\b",
    r"\bNATURAL\s+GAS\b.*\b" + _ETF_WORDS + r"\b",
    r"STANDARD\s*(&|AND)?\s*POOR",
    # UCITS copies of any fund.
    r"UCITS",
]

_RX = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]

# CUSIPs of the principal funds in scope (secondary net; names are primary).
BLOCKED_CUSIPS = frozenset(c.upper() for c in (
    "78462F103",  # SPDR S&P 500 ETF Trust (SPY)
    "464287200",  # iShares Core S&P 500 ETF (IVV)
    "922908363",  # Vanguard S&P 500 ETF (VOO)
    "922908710",  # Vanguard 500 Index Fund Admiral
    "922908108",  # Vanguard 500 Index Fund Investor
    "78464A854",  # SPDR Portfolio S&P 500 ETF (SPLG)
    "46137V357",  # Invesco S&P 500 Equal Weight ETF (RSP)
    "78355W106",  # Invesco S&P 500 Equal Weight ETF (RSP, prior CUSIP)
    "78463V107",  # SPDR Gold Trust (GLD)
    "464285105",  # iShares Gold Trust (IAU, pre-split)
    "464285204",  # iShares Gold Trust (IAU)
    "98149E303",  # SPDR Gold MiniShares (GLDM)
    "85207H104",  # Sprott Physical Gold Trust
    "81369Y506",  # Energy Select Sector SPDR Fund (XLE)
    "92204A306",  # Vanguard Energy ETF (VDE)
    "464287796",  # iShares U.S. Energy ETF (IYE)
    "78468R556",  # SPDR S&P Oil & Gas Exploration & Production ETF (XOP)
    "316092402",  # Fidelity MSCI Energy Index ETF (FENY)
))


def _norm(text: str | None) -> str:
    return " ".join((text or "").upper().split())


def is_blocked(name_of_issuer: str | None, title_of_class: str | None, cusip: str | None) -> bool:
    if _norm(cusip) in BLOCKED_CUSIPS:
        return True
    text = f"{_norm(name_of_issuer)} | {_norm(title_of_class)}"
    return any(rx.search(text) for rx in _RX)
