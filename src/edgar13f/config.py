"""Runtime configuration: cache directory and SEC User-Agent.

The server writes only inside the directory returned by `cache_dir()`:
$EDGAR13F_CACHE_DIR if set and writable, else $XDG_CACHE_HOME/edgar13f (or
~/.cache/edgar13f), else a private per-user directory under the system temp dir.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path


def _usable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        probe = path / ".write-probe"
        probe.write_bytes(b"")
        probe.unlink()
        return True
    except OSError:
        return False


def cache_dir() -> Path:
    candidates: list[Path] = []
    env = os.environ.get("EDGAR13F_CACHE_DIR")
    if env:
        candidates.append(Path(env).expanduser())
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    candidates.append(base / "edgar13f")
    for cand in candidates:
        if _usable(cand):
            return cand
        print(f"edgar13f: cache dir {cand} not writable, trying next", file=sys.stderr)
    uid = os.getuid() if hasattr(os, "getuid") else 0
    tmp = Path(tempfile.gettempdir()) / f"edgar13f-{uid}"
    if _usable(tmp) and tmp.stat().st_uid == uid:
        return tmp
    return Path(tempfile.mkdtemp(prefix="edgar13f-"))


def user_agent() -> str | None:
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    return ua or None


def write_json(path: Path, obj: object) -> None:
    """Atomic JSON write inside the cache dir (temporary name per process and thread)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}-{threading.get_ident()}")
    tmp.write_text(json.dumps(obj))
    tmp.replace(path)
