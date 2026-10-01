"""Stage 3 (a): the EDGAR13F_REDACT switch. Synthetic rows only.

Redaction is ON unless the variable is exactly "off". Tests of "off" use the invented
rows of `test_blocklist.py` (zero values, made-up CUSIPs) served by a fake client: never
live SEC data, never recorded fixtures. Only counts are asserted; no row is printed.
"""

from __future__ import annotations

import json
import re

import pytest

from edgar13f import blocklist, parse, server
from edgar13f.rules import Filing
from edgar13f.sources import EdgarSource
from tests.conftest import REPO
from tests.invariants.test_blocklist import BLOCKED, KEPT, infotable_xml, survivors

ACC = "0000000001-25-000009"
FILING = Filing(cik="1", accession_number=ACC, form_type="13F-HR", filing_date="2025-02-14",
                period_of_report="2024-12-31", primary_doc="primary_doc.xml")
NOT_OFF = [None, "", "on", "ON", "OFF", "Off", " off", "off ", "0", "false", "no", "disabled", "of"]


class _Synthetic:
    """Serves one synthetic filing; records every URL asked for."""

    def __init__(self):
        index = {"directory": {"item": [{"name": "primary_doc.xml"}, {"name": "infotable.xml"}]}}
        self.files = {"index.json": json.dumps(index).encode(), "infotable.xml": infotable_xml(BLOCKED + KEPT)}
        self.asked: list[str] = []

    def get(self, url, store=True, fetched_after=None):
        self.asked.append(url)
        return self.files.get(url.rsplit("/", 1)[-1])


def _set(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("EDGAR13F_REDACT", raising=False)
    else:
        monkeypatch.setenv("EDGAR13F_REDACT", value)


@pytest.mark.parametrize("value", NOT_OFF, ids=repr)
def test_redaction_on_unless_exactly_off(monkeypatch, tmp_path, value):
    _set(monkeypatch, value)
    assert blocklist.redacting() is True
    rows = EdgarSource(_Synthetic(), tmp_path).rows(FILING)
    assert survivors(rows) == [] and len(rows) == len(KEPT)
    assert (tmp_path / "rows" / f"{ACC}.json").exists() and not (tmp_path / "rows-unredacted").exists()


def test_off_keeps_every_synthetic_row_in_a_separate_cache(monkeypatch, tmp_path):
    _set(monkeypatch, "off")
    assert blocklist.redacting() is False
    rows = EdgarSource(_Synthetic(), tmp_path).rows(FILING)
    assert len(survivors(rows)) == len(BLOCKED) and len(rows) == len(BLOCKED) + len(KEPT)
    assert (tmp_path / "rows-unredacted" / f"{ACC}.json").exists() and not (tmp_path / "rows").exists()


def test_cache_written_with_off_is_never_read_with_redaction_on(monkeypatch, tmp_path):
    _set(monkeypatch, "off")
    EdgarSource(_Synthetic(), tmp_path).rows(FILING)
    _set(monkeypatch, None)
    client = _Synthetic()
    rows = EdgarSource(client, tmp_path).rows(FILING)
    assert survivors(rows) == [] and len(rows) == len(KEPT)
    assert any(u.endswith("infotable.xml") for u in client.asked)  # re-read and redacted, not taken from cache


def test_parse_default_redacts_whatever_the_switch(monkeypatch):
    _set(monkeypatch, "off")
    xml = infotable_xml(BLOCKED + KEPT)
    assert survivors(parse.parse_infotable(xml, ACC)) == []
    assert len(survivors(parse.parse_infotable(xml, ACC, redact=False))) == len(BLOCKED)


def test_planted_failure_switch_ignored_is_detected(monkeypatch, tmp_path):
    _set(monkeypatch, "off")
    monkeypatch.setattr(blocklist, "redacting", lambda: True)  # a switch that does nothing
    rows = EdgarSource(_Synthetic(), tmp_path).rows(FILING)
    assert len(survivors(rows)) != len(BLOCKED)  # the "off" test above would fail


def test_server_refuses_off_with_a_fixture_dir(monkeypatch, tmp_path):
    _set(monkeypatch, "off")
    monkeypatch.setenv("EDGAR13F_FIXTURE_DIR", str(tmp_path))  # empty dir: no recorded fixture is read
    with pytest.raises(SystemExit):
        server.make_source()


SETS_SWITCH = re.compile(r"""EDGAR13F_REDACT\s*[=:]|setenv\(\s*["']EDGAR13F_REDACT|["']EDGAR13F_REDACT["']\s*[]:,]""")


def test_no_ci_job_test_or_tool_sets_the_switch():
    allowed = {"tests/conftest.py", "tests/invariants/test_redact_switch.py"}
    hits = []
    for pattern in (".github/workflows/*", "tests/**/*.py", "tests/**/*.sh"):
        for path in REPO.glob(pattern):
            rel = str(path.relative_to(REPO))
            if path.is_file() and rel not in allowed and SETS_SWITCH.search(path.read_text()):
                hits.append(rel)
    assert hits == []


@pytest.mark.parametrize("line", ['  EDGAR13F_REDACT: "off"', "EDGAR13F_REDACT=off python -m edgar13f.server",
                                  'monkeypatch.setenv("EDGAR13F_REDACT", "off")', 'env={"EDGAR13F_REDACT": "off"}',
                                  'os.environ["EDGAR13F_REDACT"] = "off"'])
def test_planted_switch_settings_are_detected(line):
    assert SETS_SWITCH.search(line)
