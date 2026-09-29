"""Shared test setup. All tests run offline: outbound sockets are refused."""

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


@pytest.fixture
def fixture_source() -> FixtureSource:
    return FixtureSource(FIXTURES)
