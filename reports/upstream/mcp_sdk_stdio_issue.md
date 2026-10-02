# Draft upstream issue (not posted): stdio client reads one large message in quadratic time

Status: DRAFT for the owner; **not posted**. Target: `modelcontextprotocol/python-sdk`.
Origin: edgar13f-mcp finding F6 (`reports/STAGE_3.md`), REGISTER P8. Claims are labelled as in
CLAUDE.md; the measured ones name their command and artifact.

---

**Title:** `stdio_client`: reading one large JSON-RPC message takes time quadratic in its size
(`(buffer + chunk).split("\n")` per chunk)

### Summary

`mcp.client.stdio.stdio_client` re-concatenates and re-splits its whole pending buffer for every
chunk it reads from the server's stdout:

```python
# mcp 2.2.0, src/mcp/client/stdio.py, stdout_reader()
buffer = ""
async for chunk in stdout:
    lines = (buffer + chunk).split("\n")
    buffer = lines.pop()
    for line in lines:
        ...
```

Pipe reads return at most 64 KiB, so a single N-byte line is copied and scanned about N / 64 KiB
times: O(N^2). A 40 MB tool result (a large but ordinary `CallToolResult` whose text block and
`structuredContent` each carry ~20 MB of JSON) takes seconds to read on the client, while a plain
`readline()` reads it in a fraction of a second. The server side (`mcp.server.stdio`) reads with a
`TextIOWrapper` and is not affected.

### Environment

MEASURED (`python -m tests.tools.sdk_stdio_repro`, artifact `reports/artifacts/sdk_stdio_repro.json`):
mcp 2.2.0 (the latest 2.x on PyPI on 2026-10-02: `pip index versions mcp` lists 2.2.0 first),
anyio 4.15.1, CPython 3.11.15, linux (a cloud container), median of 3 runs per cell.

### Minimal reproduction

No MCP server is needed: the child process below is plain Python that answers one request with
a JSON-RPC result holding an N-byte string.

```python
# repro.py  (pip install "mcp==2.2.0")
import sys
import time

import anyio
import mcp_types
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.message import SessionMessage

CHILD = r"""
import sys
blob = "x" * int(sys.argv[1])
sys.stdin.readline()
sys.stdout.write('{"jsonrpc":"2.0","id":1,"result":{"blob":"' + blob + '"}}\n')
sys.stdout.flush()
sys.stdin.readline()
"""


async def main(mb: float) -> None:
    params = StdioServerParameters(command=sys.executable, args=["-c", CHILD, str(int(mb * 1_000_000))])
    async with stdio_client(params) as (read, write):
        t0 = time.perf_counter()
        await write.send(SessionMessage(mcp_types.JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")))
        await read.receive()
        print(f"{mb:>4} MB line: {time.perf_counter() - t0:.2f} s")


for mb in (1, 5, 10, 20, 40):
    anyio.run(main, mb)
```

### Measured

MEASURED (`reports/artifacts/sdk_stdio_repro.json`). Time from sending the request to holding the parsed
message; both loops end in the SDK's own `_parse_line` (JSON-RPC validation). Doubling the
line from 20 to 40 MB multiplies the SDK client's time by about 5.7; the fixed loop stays
within about 1.4x of `readline()`.

| Line size | `stdio_client` (unmodified) | SDK reader loop, copied | same loop with the fix below | `readline()` |
|---|---|---|---|---|
| 1 MB | 0.03 s | 0.02 s | 0.02 s | 0.02 s |
| 2 MB | 0.04 s | 0.04 s | 0.03 s | 0.02 s |
| 5 MB | 0.19 s | 0.15 s | 0.06 s | 0.05 s |
| 10 MB | 0.46 s | 0.45 s | 0.10 s | 0.08 s |
| 20 MB | 1.57 s | 1.53 s | 0.15 s | 0.15 s |
| 40 MB | 8.94 s | 9.38 s | 0.37 s | 0.27 s |

In a real server (edgar13f-mcp, a ~40 MB `CallToolResult` with text and `structuredContent`)
the same client took 5.9-11.9 s per warm call, against about 1 s with a `readline()` client
(MEASURED: `sdk_stdio_warm_s` in `reports/artifacts/agent_latency_run1.json`, and
`reports/artifacts/cold_latency_stage3_after_run1.json`).

### Suggested fix

Keep the partial line as a list of chunks and join it once, when its newline arrives. Each byte
is then copied a constant number of times (linear in the message size); behaviour is otherwise
unchanged (same lines, same order, same back-pressure: still one delivery at a time, no
read-ahead while `send` blocks).

```diff
-                    buffer = ""
+                    pending: list[str] = []
                     async for chunk in stdout:
-                        lines = (buffer + chunk).split("\n")
-                        buffer = lines.pop()
+                        *lines, tail = chunk.split("\n")
+                        if lines:
+                            lines[0] = "".join(pending) + lines[0]
+                            pending = []
+                        if tail:
+                            pending.append(tail)
                         for line in lines:
```

A regression test can feed one 20-40 MB line through `stdio_client` (as in the reproduction) and
assert a generous bound, or feed `stdout_reader` a stream of many small chunks without a newline
and count the bytes copied.

### Related

Servers can avoid the cost by keeping results small; edgar13f-mcp added `max_positions` and an
agent mode for that (its Addendum A2/A5), but large results are legitimate MCP messages and
clients should read them in linear time.
