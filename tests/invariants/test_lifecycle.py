"""Stage 5 (b): server lifecycle over stdio, offline.

* Closing stdin ends the server within 10 s with exit code 0.
* A malformed JSON-RPC line gets a JSON-RPC error or is ignored; the server keeps answering.
* SIGTERM, then separately SIGKILL, mid-call: the client sees a clean error, the cache holds
  no partial or corrupt file, and a fresh start answers correctly from the same cache.

Each check is a function that returns its problems; each runs on the real server (no problem)
and on a planted defect (at least one problem). The mid-call checks use
`tests.invariants.lifecycle_server`: the real stdio loop, EdgarSource and SecClient, answered
from the synthetic manager by an offline opener that can hold an information table in flight.
"""

from __future__ import annotations

import json
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from edgar13f import DISCLAIMER, parse, tools
from edgar13f.sources import FixtureSource
from tests.conftest import REPO
from tests.invariants import lifecycle_server as ls

SERVER = [sys.executable, "-m", "edgar13f.server"]
OFFLINE = [sys.executable, "-m", "tests.invariants.lifecycle_server"]
CALL = ("get_holdings_as_of", {"cik": "9900000001", "period": "2024-06-30", "as_of": "2025-01-01"})
BAD_LINES = [b"{not json", b'{"jsonrpc":"2.0","id":7,"method":"tools/call","params":', b"[]",
             b'{"jsonrpc":"2.0","id":8}', b"\xff\xfe garbage", b'{"jsonrpc":"1.0","id":9,"method":"tools/list"}']


def _env(cache: Path, **extra: str) -> dict[str, str]:
    env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(REPO), "EDGAR13F_CACHE_DIR": str(cache),
           "EDGAR13F_FIXTURE_DIR": str(ls.FIXTURES)}
    return {**env, **extra}


class Raw:
    """Newline-delimited JSON-RPC over a child's stdin/stdout, with timeouts."""

    def __init__(self, cmd: list[str], env: dict[str, str]):
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, env=env, cwd=REPO)
        self.next_id = 100

    def send(self, line: bytes | dict) -> None:
        data = line if isinstance(line, bytes) else json.dumps(line).encode()
        try:
            self.proc.stdin.write(data + b"\n")
            self.proc.stdin.flush()
        except BrokenPipeError:  # the server is gone; the missing answer is the observation
            pass

    def lines(self, timeout: float):
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            if not select.select([self.proc.stdout], [], [], left)[0]:
                return
            line = self.proc.stdout.readline()
            if not line:
                return
            yield line

    def request(self, method: str, params: dict | None = None, timeout: float = 10.0) -> tuple[dict | None, list]:
        """Send a request; return (its response or None, every other line read meanwhile)."""
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": self.next_id, "method": method, "params": params or {}})
        other = []
        for line in self.lines(timeout):
            msg = json.loads(line)
            if msg.get("id") == self.next_id:
                return msg, other
            other.append(msg)
        return None, other

    def handshake(self) -> bool:
        resp, _ = self.request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                              "clientInfo": {"name": "lifecycle-test", "version": "0"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return bool(resp and "result" in resp)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        for pipe in (self.proc.stdin, self.proc.stdout):
            try:
                pipe.close()
            except OSError:
                pass


def _answers(raw: Raw) -> list[str]:
    """A tools/list and one tools/call must come back correct."""
    problems = []
    listed, _ = raw.request("tools/list")
    if not listed or {t["name"] for t in listed.get("result", {}).get("tools", [])} != set(tools.TOOLS):
        problems.append(f"tools/list not answered correctly: {str(listed)[:200]}")
    called, _ = raw.request("tools/call", {"name": "list_13f_filings", "arguments": {"cik": "9900000001",
                                                                                     "as_of": "2025-01-01"}})
    body = (called or {}).get("result", {}).get("structuredContent") or {}
    if body.get("status") != "ok" or body.get("disclaimer") != DISCLAIMER:
        problems.append(f"tools/call not answered correctly: {str(called)[:200]}")
    return problems


def stdin_close_problems(cmd: list[str], env: dict[str, str], limit: float = 10.0) -> list[str]:
    raw = Raw(cmd, env)
    try:
        if not raw.handshake():
            return ["no initialize response"]
        problems = _answers(raw)
        start = time.monotonic()
        raw.proc.stdin.close()
        try:
            code = raw.proc.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            return problems + [f"still running {limit:.0f} s after stdin was closed"]
        if code != 0:
            problems.append(f"exit code {code} after stdin was closed")
        if time.monotonic() - start > limit:
            problems.append("exit took longer than the limit")
        return problems
    finally:
        raw.close()


def malformed_problems(cmd: list[str], env: dict[str, str]) -> list[str]:
    raw = Raw(cmd, env)
    try:
        if not raw.handshake():
            return ["no initialize response"]
        problems = []
        for bad in BAD_LINES:
            if raw.proc.poll() is not None:
                return problems + [f"server exited (code {raw.proc.returncode}) after {bad[:30]!r}"]
            raw.send(bad)
            try:
                for line in raw.lines(1.0):  # anything sent back must be a JSON-RPC error
                    msg = json.loads(line)
                    if msg.get("jsonrpc") != "2.0" or "error" not in msg:
                        problems.append(f"{bad[:30]!r} -> not a JSON-RPC error: {line[:200]!r}")
            except ValueError:
                problems.append(f"{bad[:30]!r} -> a line that is not JSON")
            got = _answers(raw)
            problems += [f"after {bad[:30]!r}: {p}" for p in got]
        return problems
    finally:
        raw.close()


def _expected() -> dict:
    return tools.call(FixtureSource(ls.FIXTURES), *CALL)


def cache_problems(cache: Path, inflate: int = 1) -> list[str]:
    """Every file the cache holds must be whole: HTTP bodies byte-identical to what was served,
    rows equal to the parsed table, log lines whole JSON; no temporary file left over."""
    files = ls.fake_edgar(inflate=inflate)
    by_key = {ls.cache_key(url): body for url, body in files.items()}
    tables = {url.split("/")[-2]: body for url, body in files.items() if url.endswith("/infotable.xml")}
    problems = []
    for path in sorted(p for p in cache.rglob("*") if p.is_file()):
        rel = path.relative_to(cache).as_posix()
        if ".tmp" in path.name:
            problems.append(f"temporary file left: {rel}")
        elif rel.startswith("http/"):
            if by_key.get(path.name) != path.read_bytes():
                problems.append(f"HTTP cache entry not byte-identical to the body served: {rel}")
        elif rel.startswith("rows/"):
            acc = path.name.removesuffix(".json")
            try:
                rows = json.loads(path.read_text())
            except ValueError:
                problems.append(f"rows file is not whole JSON: {rel}")
                continue
            if rows != parse.parse_infotable(tables[acc.replace("-", "")], acc):
                problems.append(f"rows file differs from the information table: {rel}")
        elif rel == "requests.log":
            for n, line in enumerate(path.read_text().splitlines(), 1):
                try:
                    assert set(json.loads(line)) == {"t", "url", "status"}
                except (ValueError, AssertionError):
                    problems.append(f"requests.log line {n} is not a whole record")
        elif rel != "ratelimit.lock":
            problems.append(f"unexpected file in the cache: {rel}")
    return problems


async def _call_and_signal(env: dict[str, str], marker: Path, sig: int, limit: float):
    """Call CALL; once a request is in flight (marker), send `sig` to the server. Returns
    (exception class name or None, seconds from the signal to the client's error, server pid)."""
    params = StdioServerParameters(command=OFFLINE[0], args=OFFLINE[1:], env=env, cwd=str(REPO))
    out = {"error": None, "seconds": None, "pid": None}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def signal_when_in_flight():
                while not marker.exists() or not marker.read_text():
                    await anyio.sleep(0.02)
                out["pid"] = int(marker.read_text().split()[0])
                out["sent"] = time.monotonic()
                os.kill(out["pid"], sig)

            async with anyio.create_task_group() as tg:
                tg.start_soon(signal_when_in_flight)
                try:
                    with anyio.fail_after(limit + 5):
                        await session.call_tool(*CALL)
                    out["error"] = "no error: the call returned"
                except TimeoutError:
                    out["error"] = None
                except Exception as exc:  # noqa: BLE001 - the class is the observation
                    out["error"] = type(exc).__name__
                    out["seconds"] = time.monotonic() - out.get("sent", time.monotonic())
                tg.cancel_scope.cancel()
    return out


def mid_call_problems(tmp: Path, sig: int, plant: str = "", limit: float = 10.0) -> tuple[list[str], dict]:
    cache, marker = tmp / "cache", tmp / "in-flight"
    env = _env(cache, LIFECYCLE_MARKER=str(marker), LIFECYCLE_SLOW_AFTER="1", LIFECYCLE_PLANT=plant)
    env.pop("EDGAR13F_FIXTURE_DIR")
    if plant == "partial-write":
        env.pop("LIFECYCLE_SLOW_AFTER")
    try:
        seen = anyio.run(_call_and_signal, env, marker, sig, limit)
    except BaseException as exc:  # noqa: BLE001 - an error escaping the client is itself a finding
        seen = {"error": f"escaped: {type(exc).__name__}", "seconds": None, "pid": None}
    pid = seen.get("pid") or (int(marker.read_text().split()[0]) if marker.exists() else None)
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)  # ignore-sigterm control: clean up after the observation
        except ProcessLookupError:
            pass
    problems = []
    if seen["error"] != "MCPError" or seen["seconds"] is None or seen["seconds"] > limit:
        problems.append(f"client did not see a clean error within {limit:.0f} s: {seen}")
    problems += cache_problems(cache)
    before = {p.name for p in (cache / "http").iterdir()} if (cache / "http").exists() else set()
    log_path = cache / "requests.log"
    logged = len(log_path.read_text().splitlines()) if log_path.exists() else 0
    raw = Raw(OFFLINE, {k: v for k, v in env.items() if not k.startswith("LIFECYCLE_")})
    try:
        if not raw.handshake():
            problems.append("fresh start: no initialize response")
        resp, _ = raw.request("tools/call", {"name": CALL[0], "arguments": CALL[1]}, timeout=30)
        result = (resp or {}).get("result", {})
        if result.get("isError") is not False or result.get("structuredContent") != _expected():
            problems.append(f"fresh start: wrong answer: {str(resp)[:300]}")
    finally:
        raw.close()
    after = log_path.read_text().splitlines()[logged:] if log_path.exists() else []
    refetched = [r["url"] for r in map(json.loads, after) if ls.cache_key(r["url"]) in before]
    if refetched and not problems:
        problems.append(f"fresh start fetched cached documents again: {refetched[:3]}")
    return problems, seen


# --- stdin close -------------------------------------------------------------------------------

def test_stdin_close_exits_zero_within_10s(tmp_path):
    assert stdin_close_problems(SERVER, _env(tmp_path / "cache")) == []


def test_stdin_close_offline_live_source_exits_zero(tmp_path):
    env = _env(tmp_path / "cache")
    assert stdin_close_problems(OFFLINE, {k: v for k, v in env.items() if k != "EDGAR13F_FIXTURE_DIR"}) == []


def test_planted_server_ignoring_stdin_close_is_caught(tmp_path):
    env = _env(tmp_path / "cache", LIFECYCLE_PLANT="ignore-stdin-eof")
    env.pop("EDGAR13F_FIXTURE_DIR")
    problems = stdin_close_problems(OFFLINE, env, limit=3.0)
    assert any("still running" in p for p in problems), problems


# --- malformed JSON-RPC ------------------------------------------------------------------------

def test_malformed_lines_are_ignored_or_errors_and_server_keeps_answering(tmp_path):
    assert malformed_problems(SERVER, _env(tmp_path / "cache")) == []


def test_planted_server_dying_on_malformed_line_is_caught(tmp_path):
    env = _env(tmp_path / "cache", LIFECYCLE_PLANT="exit-on-garbage")
    env.pop("EDGAR13F_FIXTURE_DIR")
    problems = malformed_problems(OFFLINE, env)
    assert any("exited" in p or "not answered" in p for p in problems), problems


# --- SIGTERM / SIGKILL mid-call ----------------------------------------------------------------

@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGKILL], ids=["SIGTERM", "SIGKILL"])
def test_signal_mid_call_clean_error_whole_cache_fresh_start(tmp_path, sig):
    problems, seen = mid_call_problems(tmp_path, sig)
    assert problems == [], problems
    assert (tmp_path / "cache" / "rows").exists(), "the kill must land after a rows file was written"


def test_planted_server_ignoring_sigterm_is_caught(tmp_path):
    problems, _ = mid_call_problems(tmp_path, signal.SIGTERM, plant="ignore-sigterm", limit=3.0)
    assert any("client did not see a clean error" in p for p in problems), problems


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGKILL], ids=["SIGTERM", "SIGKILL"])
def test_planted_partial_cache_write_is_caught(tmp_path, sig):
    problems, _ = mid_call_problems(tmp_path, sig, plant="partial-write")
    assert any("rows file is not whole JSON" in p for p in problems), problems
    assert any(p.startswith("fresh start: wrong answer") for p in problems), problems


def test_offline_edgar_round_trips_the_synthetic_rows():
    """The fake information tables parse back to the recorded synthetic rows (else the cache check is void)."""
    files = ls.fake_edgar()
    for path in sorted((ls.FIXTURES / "9900000001" / "rows").glob("*.json")):
        acc = path.stem
        url = f"{ls.ARCHIVES}/9900000001/{acc.replace('-', '')}/infotable.xml"
        assert parse.parse_infotable(files[url], acc) == json.loads(path.read_text())


# --- stale temporary files (found by tests/tools/kill_fuzz.py: a kill between write and rename) ----

def test_fresh_start_removes_temp_files_of_dead_processes_only(tmp_path):
    """A kill inside a cache write leaves `<name>.tmp<pid>-<thread>` (never read, never renamed).
    A fresh start must remove those of dead processes and keep those of live ones (their rename
    may still come)."""
    cache = tmp_path / "cache"
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    stale = [cache / "rows" / f"9900000001-24-000004.tmp{dead.pid}-1", cache / "http" / f"{'a' * 64}.tmp{dead.pid}-2"]
    live = cache / "rows" / f"9900000001-24-000003.tmp{os.getpid()}-3"
    for path in stale + [live]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"half": ')
    env = {k: v for k, v in _env(cache).items() if k != "EDGAR13F_FIXTURE_DIR"}
    raw = Raw(OFFLINE, env)
    try:
        assert raw.handshake()
        resp, _ = raw.request("tools/call", {"name": CALL[0], "arguments": CALL[1]}, timeout=30)
        assert resp["result"]["structuredContent"] == _expected()
    finally:
        raw.close()
    assert [p.name for p in stale if p.exists()] == []
    assert live.exists()
