"""Shared test setup. All tests run offline: outbound sockets are refused, and every test
starts with EDGAR13F_REDACT unset (redaction ON) and EDGAR13F_AGENT_MODE unset. Tests of
EDGAR13F_REDACT=off set it on synthetic rows only."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from edgar13f.sources import FixtureSource

FIXTURES = Path(__file__).resolve().parent / "fixtures"
REPO = Path(__file__).resolve().parents[1]


class NetworkBlocked(RuntimeError):
    pass


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise NetworkBlocked("network access is disabled in tests")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    monkeypatch.delenv("EDGAR13F_REDACT", raising=False)
    monkeypatch.delenv("EDGAR13F_AGENT_MODE", raising=False)


@pytest.fixture
def fixture_source() -> FixtureSource:
    return FixtureSource(FIXTURES)
