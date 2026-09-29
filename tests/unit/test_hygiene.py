"""Hard rule 6: no filer-specific literals (CIKs, accession numbers, dates) in src/."""

import re

from tests.conftest import REPO

ACCESSION = re.compile(r"\b\d{10}-\d{2}-\d{6}\b")
ISO_DATE = re.compile(r"\b(19|20)\d{2}-[01]\d-[0-3]\d\b")
CIK_LIKE = re.compile(r"(?<![\w.])\d{6,10}(?![\w.])")


def test_no_filer_specific_literals_in_src():
    hits = []
    for path in sorted((REPO / "src").rglob("*.py")):
        for no, line in enumerate(path.read_text().splitlines(), 1):
            code = line.split("#", 1)[0]
            if path.name == "blocklist.py" and re.search(r'"[0-9A-Z]{9}",', code):
                continue  # CUSIP list of blocklisted funds (hard rule 2), not filers
            if ACCESSION.search(line) or ISO_DATE.search(line) or CIK_LIKE.search(code):
                hits.append(f"{path.name}:{no}")
    assert hits == []
