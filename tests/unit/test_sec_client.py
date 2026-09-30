"""Fair-access behaviour of SecClient with a fake opener (no network)."""

import bisect
import json
import os
import time

import pytest

from edgar13f import sec_client
from edgar13f.sec_client import SecClient, SecUnavailable

UA = "edgar13f-tests test@example.com"


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, req, timeout):
        self.calls.append((time.time(), req.full_url, req.get_header("User-agent")))
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        return item[0], item[1], {}


def client(tmp_path, responses, ua=UA, **kw):
    opener = FakeOpener(responses)
    sleeps = []
    c = SecClient(tmp_path, ua, opener=opener, sleep=sleeps.append, **kw)
    return c, opener, sleeps


def test_user_agent_from_env_value_is_sent(tmp_path):
    c, op, _ = client(tmp_path, [(200, b"{}")])
    assert c.get("https://data.sec.gov/x.json") == b"{}"
    assert op.calls[0][2] == UA


def test_no_user_agent_refuses_to_fetch(tmp_path):
    c, op, _ = client(tmp_path, [(200, b"{}")], ua=None)
    with pytest.raises(SecUnavailable):
        c.get("https://data.sec.gov/x.json")
    assert op.calls == []


@pytest.mark.parametrize("bad", [
    (403, b"Forbidden"),
    (429, b"slow down"),
    (503, b""),
    (200, b"<!DOCTYPE html><html><body>Request Rate Threshold Exceeded</body></html>"),
    (200, b"  <html><head><title>SEC.gov | Error</title></head></html>"),
])
def test_retryable_then_success_with_exponential_backoff(tmp_path, bad):
    c, op, sleeps = client(tmp_path, [bad, bad, bad, (200, b"<ok/>")])
    assert c.get("https://www.sec.gov/a.xml") == b"<ok/>"
    assert len(op.calls) == 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_gives_up_after_max_retries(tmp_path):
    c, op, sleeps = client(tmp_path, [(429, b"")], max_retries=3)
    with pytest.raises(SecUnavailable):
        c.get("https://www.sec.gov/a.xml")
    assert len(op.calls) == 4 and sleeps == [1.0, 2.0, 4.0]


def test_404_returns_none_without_retry(tmp_path):
    c, op, _ = client(tmp_path, [(404, b"")])
    assert c.get("https://data.sec.gov/CIK0000000000.json") is None
    assert len(op.calls) == 1


def test_disk_cache_and_store_false(tmp_path):
    c, op, _ = client(tmp_path, [(200, b"<a/>")])
    c.get("https://www.sec.gov/p.xml")
    c.get("https://www.sec.gov/p.xml")
    assert len(op.calls) == 1
    c.get("https://www.sec.gov/infotable.xml", store=False)
    c.get("https://www.sec.gov/infotable.xml", store=False)
    assert len(op.calls) == 3
    assert len(list((tmp_path / "http").iterdir())) == 1


def test_fetched_after_forces_refresh_of_stale_copy(tmp_path):
    c, op, _ = client(tmp_path, [(200, b"{}")])
    c.get("https://data.sec.gov/s.json")
    path = next((tmp_path / "http").iterdir())
    os.utime(path, (1_000_000, 1_000_000))
    c.get("https://data.sec.gov/s.json", fetched_after=2_000_000)
    assert len(op.calls) == 2
    c.get("https://data.sec.gov/s.json", fetched_after=2_000_000)
    assert len(op.calls) == 2


def test_rate_limit_at_most_five_per_second_and_logged(tmp_path, monkeypatch):
    c, op, _ = client(tmp_path, [(200, b"{}")])
    for i in range(12):
        c.get(f"https://data.sec.gov/{i}.json")
    ts = [t for t, _, _ in op.calls]
    worst = max(bisect.bisect_left(ts, t + 1.0) - i for i, t in enumerate(ts))
    assert worst <= 5
    log = [json.loads(line) for line in (tmp_path / "requests.log").read_text().splitlines()]
    assert len(log) == 12 and all(entry["status"] == 200 for entry in log)


def test_rate_limit_shared_across_client_instances(tmp_path):
    a, op_a, _ = client(tmp_path, [(200, b"{}")])
    b, op_b, _ = client(tmp_path, [(200, b"{}")])
    for i in range(6):
        (a if i % 2 else b).get(f"https://data.sec.gov/{i}.json")
    ts = sorted(t for t, _, _ in op_a.calls + op_b.calls)
    assert all(t2 - t1 >= sec_client.MIN_INTERVAL - 0.01 for t1, t2 in zip(ts, ts[1:]))


def test_html_detection():
    assert sec_client.looks_like_html(b"\n<!doctype HTML>")
    assert not sec_client.looks_like_html(b'<?xml version="1.0"?><informationTable/>')
    assert not sec_client.looks_like_html(b'{"a": 1}')


def test_rate_limit_holds_under_concurrent_threads(tmp_path):
    import threading

    c, op, _ = client(tmp_path, [(200, b"{}")])
    threads = [threading.Thread(target=lambda k=k: [c.get(f"https://data.sec.gov/{k}-{i}.json") for i in range(4)])
               for k in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ts = sorted(t for t, _, _ in op.calls)
    assert len(ts) == 16
    assert max(bisect.bisect_left(ts, t + 1.0) - i for i, t in enumerate(ts)) <= 5
