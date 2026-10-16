"""Planted failure for the inspector job: the real server with `find_manager` left out of tools/list
(it can still be called). `tests/inspector/inspector_check.sh` must fail on it."""

from edgar13f import server

server.TOOL_DEFS.pop("find_manager")

if __name__ == "__main__":
    server.main()
