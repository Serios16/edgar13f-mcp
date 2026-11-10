# Upstream issue (not posted): stdio client reads one large message in quadratic time

Status: **still reproduces on mcp 2.3.0, the newest 2.x** (stage 7a, 2026-11-10). An open upstream
issue already covers it, so the owner should **comment on it rather than file a new issue**.
Nothing has been posted. Target: `modelcontextprotocol/python-sdk`. Origin: edgar13f-mcp finding
F6 (`reports/STAGE_3.md`), REGISTER P8. Labels as in CLAUDE.md.

## Stage 7a check

* Versions tested: 2.2.0 and 2.3.0. `pip index versions mcp` lists 2.3.0 first (REPORTED by the package
  index on 2026-11-10; the 2.x line is 2.0.0, 2.0.1, 2.1.0, 2.1.1, 2.2.0, 2.3.0).
* Reproduces: **yes, on both.** MEASURED (`reports/artifacts/sdk_stdio_repro_stage7a.txt`, one venv per version,
  `python -m tests.tools.sdk_stdio_repro`). A 40 MB line takes 12.1 s
  through `stdio_client` on 2.2.0 and on 2.3.0, against 0.31-0.34 s for `readline()` and for the
  fixed loop. 20 MB takes 2.6 s. Doubling 20 to 40 MB multiplies the time by about 4.6-4.7.
* Source: REASONED from reading the installed 2.3.0 wheel, module mcp.client.stdio, line 152: `stdout_reader()`
  still runs `lines = (buffer + chunk).split("\n")`.
* Related upstream items (REPORTED, from GitHub issue search and the public pages on 2026-11-10;
  not posted to):
  * [#3699](https://github.com/modelcontextprotocol/python-sdk/issues/3699), **open**, labels
    `bug`, `v1`, `v2`. "stdio_client: receiving a large response takes quadratic time (buffer +
    chunk is re-copied for every chunk)", opened 2026-10-13 against 2.3.0 with the same diagnosis
    and the same list-join fix (16 MB: 5.39 s, then 0.27 s). Comments on it confirm the cost on main
    (32 MB: 45.72 s, then 0.79 s) and note that v1.x has the same loop. No linked PR, no assignee,
    no fix released.
  * PRs [#3700](https://github.com/modelcontextprotocol/python-sdk/pull/3700),
    [#3705](https://github.com/modelcontextprotocol/python-sdk/pull/3705) and
    [#3706](https://github.com/modelcontextprotocol/python-sdk/pull/3706): all **closed, not
    merged**. #3700 was closed the same day by the repository bot because its author was not
    assigned to #3699 (label `missing-issue-link`); I read only that one page. #3705 and #3706 are
    listed as closed by the issue search and were not opened.
  * [#3330](https://github.com/modelcontextprotocol/python-sdk/issues/3330) (open) is about an
    unbounded message size on streamable HTTP, a different problem.
* Not fixed in any version, so there is no "fixed in" to report.

## What to post

Comment on #3699 with the edgar13f data below (a server that returns real 40 MB results, and a
reproduction with no MCP server), rather than a duplicate issue. The comment adds: both versions
measured, the 40 MB point, the end-to-end effect, and the loop-level proof that the fix is
linear. The original body follows as the ready-to-paste text; trim the title and Summary to one
line if posting as a comment.

---

**Title:** `stdio_client`: reading one large JSON-RPC message takes time quadratic in its size
(`(buffer + chunk).split("\n")` per chunk)

### Summary

`mcp.client.stdio.stdio_client` re-concatenates and re-splits its whole pending buffer for every
chunk it reads from the server's stdout:

```python
# mcp 2.2.0 and 2.3.0, src/mcp/client/stdio.py, stdout_reader()
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
mcp 2.2.0 and 2.3.0 (2.3.0 is the latest 2.x on PyPI on 2026-11-10; both behave the same,
`reports/artifacts/sdk_stdio_repro_stage7a.txt`), anyio 4.16.0, CPython 3.11.18, linux (a cloud
container), median of 3 runs per cell. The table below is the stage 4 run on 2.2.0
(`reports/artifacts/sdk_stdio_repro.json`); the stage 7a run on 2.3.0 gives 12.1 s at 40 MB.

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
