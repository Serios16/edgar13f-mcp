"""F6 reproduction (stage 4): the MCP Python SDK stdio client needs time quadratic in the size
of one JSON-RPC line. Synthetic payload only (no SEC data); no edgar13f code is involved.

  python -m tests.tools.sdk_stdio_repro --sizes 1,2,5,10,20,40 --repeat 3 \
      --out reports/artifacts/sdk_stdio_repro.json

A child process (plain Python, no SDK) answers one request with a JSON-RPC result whose only
field is a string of N MB. Four readers time the same answer, from sending the request to
holding the parsed message:
  sdk          mcp.client.stdio.stdio_client, unmodified (write a request, receive the message);
  sdk_loop     the SDK's reader loop copied verbatim, over the same anyio TextReceiveStream;
  fixed_loop   the same loop with the suggested fix (pending chunks joined once a newline arrives);
  readline     a blocking readline() on the pipe (lower bound).
Both loops end in the SDK's own JSON-RPC validation (`mcp.client.stdio._parse_line`).
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path

import anyio
from anyio.streams.text import TextReceiveStream

CHILD = r"""
import sys
blob = "x" * int(sys.argv[1])
sys.stdin.readline()
sys.stdout.write('{"jsonrpc":"2.0","id":1,"result":{"blob":"' + blob + '"}}\n')
sys.stdout.flush()
sys.stdin.readline()
"""
REQUEST = '{"jsonrpc":"2.0","id":1,"method":"ping"}\n'


async def sdk(size: int) -> float:
    import mcp_types
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.shared.message import SessionMessage

    params = StdioServerParameters(command=sys.executable, args=["-c", CHILD, str(size)])
    async with stdio_client(params) as (read, write):
        t0 = time.perf_counter()
        await write.send(SessionMessage(mcp_types.JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")))
        msg = await read.receive()
        elapsed = time.perf_counter() - t0
    assert not isinstance(msg, Exception)
    return elapsed


async def sdk_loop(stdout: TextReceiveStream) -> list:
    from mcp.client.stdio import _parse_line

    out = []
    buffer = ""  # mcp 2.2.0, mcp/client/stdio.py, stdout_reader()
    async for chunk in stdout:
        lines = (buffer + chunk).split("\n")
        buffer = lines.pop()
        for line in lines:
            out.append(_parse_line(line))
        if out:
            return out
    return out


async def fixed_loop(stdout: TextReceiveStream) -> list:
    from mcp.client.stdio import _parse_line

    out = []
    pending: list[str] = []  # suggested fix: a line is joined once, when its newline arrives
    async for chunk in stdout:
        *lines, tail = chunk.split("\n")
        if lines:
            lines[0] = "".join(pending) + lines[0]
            pending = []
            for line in lines:
                out.append(_parse_line(line))
        if tail:
            pending.append(tail)
        if out:
            return out
    return out


async def loop(size: int, reader) -> float:
    proc = await anyio.open_process([sys.executable, "-c", CHILD, str(size)])
    async with proc:
        stdout = TextReceiveStream(proc.stdout, encoding="utf-8")
        t0 = time.perf_counter()
        await proc.stdin.send(REQUEST.encode())
        msgs = await reader(stdout)
        elapsed = time.perf_counter() - t0
        await proc.stdin.send(b"\n")
    assert len(msgs) == 1 and not isinstance(msgs[0], Exception)
    return elapsed


def readline(size: int) -> float:
    proc = subprocess.Popen([sys.executable, "-c", CHILD, str(size)], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    t0 = time.perf_counter()
    proc.stdin.write(REQUEST.encode())
    proc.stdin.flush()
    json.loads(proc.stdout.readline())
    elapsed = time.perf_counter() - t0
    proc.communicate(b"\n")
    return elapsed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--sizes", default="1,2,5,10,20,40", help="payload sizes in MB")
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    rows = []
    for mb in [float(x) for x in a.sizes.split(",")]:
        size = int(mb * 1_000_000)
        runs = {"sdk": [], "sdk_loop": [], "fixed_loop": [], "readline": []}
        for _ in range(a.repeat):
            runs["sdk"].append(anyio.run(sdk, size))
            runs["sdk_loop"].append(anyio.run(loop, size, sdk_loop))
            runs["fixed_loop"].append(anyio.run(loop, size, fixed_loop))
            runs["readline"].append(readline(size))
        row = {"payload_mb": mb, **{k: {"median_s": round(statistics.median(v), 3), "runs_s": [round(x, 3) for x in v]}
                                    for k, v in runs.items()}}
        rows.append(row)
        print(json.dumps(row), flush=True)
    a.out.write_text(json.dumps({"mcp": version("mcp"), "anyio": version("anyio"), "python": sys.version.split()[0],
                                 "platform": sys.platform, "repeat": a.repeat, "results": rows}, indent=1) + "\n")


if __name__ == "__main__":
    main()
