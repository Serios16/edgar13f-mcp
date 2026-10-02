"""SEC EDGAR HTTP client with fair-access controls.

* User-Agent comes from $SEC_USER_AGENT (no default; requests fail without it).
* At most 5 requests/second across every process sharing the cache dir: request
  starts are spaced >= MIN_INTERVAL apart; the fcntl lock on a shared file is held
  from the wait until the request has been sent, so scheduling jitter cannot
  bunch sends together.
* Exponential backoff on 403, 429, 5xx, network errors, truncated bodies
  (http.client.IncompleteRead and other HTTPException), and HTML error pages served
  in place of the JSON/XML that was asked for.
* On-disk cache keyed by URL; every network request is appended to requests.log.
"""

from __future__ import annotations

import fcntl
import hashlib
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

MIN_INTERVAL = 0.25  # seconds between request starts => at most 4 starts in any 1 s window
RETRYABLE_STATUS = {403, 429, 500, 502, 503, 504}


class SecUnavailable(RuntimeError):
    """sec.gov could not be reached after all retries (or no User-Agent is set)."""


def looks_like_html(body: bytes) -> bool:
    head = body[:512].lstrip().lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


class SecClient:
    def __init__(
        self,
        cache: Path,
        user_agent: str | None,
        *,
        opener: Callable[[urllib.request.Request, float], tuple[int, bytes, dict]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_retries: int = 6,
        backoff_base: float = 1.0,
    ) -> None:
        self.cache = cache
        self.user_agent = user_agent
        self.opener = opener or _urlopen
        self.sleep = sleep
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        (cache / "http").mkdir(parents=True, exist_ok=True)
        self.lock_path = cache / "ratelimit.lock"
        self.log_path = cache / "requests.log"

    def _cache_path(self, url: str) -> Path:
        return self.cache / "http" / hashlib.sha256(url.encode()).hexdigest()

    def get(self, url: str, *, store: bool = True, fetched_after: float | None = None,
            headers: dict | None = None) -> bytes | None:
        """Return the body of `url` (JSON/XML expected) or None on 404.

        store=False keeps the body out of the on-disk cache (used for information
        tables, which are cached only after blocklist redaction, and for byte ranges).
        fetched_after: a cached copy is used only if it was fetched at or after this
        epoch time (point-in-time freshness for mutable documents).
        headers: extra request headers (e.g. Range; a 206 answer counts as success).
        """
        path = self._cache_path(url)
        store = store and not headers
        if store and path.exists():
            if fetched_after is None or path.stat().st_mtime >= fetched_after:
                return path.read_bytes()
        body = self._fetch(url, headers or {})
        if body is not None and store:
            tmp = path.with_suffix(f".tmp{os.getpid()}")
            tmp.write_bytes(body)
            tmp.replace(path)
        return body

    def _fetch(self, url: str, headers: dict) -> bytes | None:
        if not self.user_agent:
            raise SecUnavailable("SEC_USER_AGENT is not set; refusing to contact sec.gov")
        last = "no attempt"
        for attempt in range(self.max_retries + 1):
            if attempt:
                self.sleep(self.backoff_base * (2 ** (attempt - 1)))
            req = urllib.request.Request(url, headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "identity",
                **headers,
            })
            try:
                status, body, _ = self._throttled(req)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.HTTPException) as exc:
                self._log(url, f"neterr:{type(exc).__name__}")
                last = repr(exc)
                continue
            self._log(url, status)
            if status == 404:
                return None
            if status in RETRYABLE_STATUS:
                last = f"HTTP {status}"
                continue
            if status not in (200, 206):
                raise SecUnavailable(f"unexpected HTTP {status} for {url}")
            if looks_like_html(body):
                last = "HTML error page in place of data"
                continue
            return body
        raise SecUnavailable(f"giving up on {url}: {last}")

    def _throttled(self, req: urllib.request.Request) -> tuple[int, bytes, dict]:
        with open(self.lock_path, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            try:
                last = float(fh.read().strip() or 0.0)
            except ValueError:
                last = 0.0
            wait = last + MIN_INTERVAL - time.time()
            if wait > 0:
                time.sleep(wait)
            fh.seek(0)
            fh.truncate()
            fh.write(repr(time.time()))
            fh.flush()
            return self.opener(req, 30.0)

    def _log(self, url: str, status: object) -> None:
        with open(self.log_path, "a") as fh:
            fh.write(json.dumps({"t": time.time(), "url": url, "status": status}) + "\n")


def _urlopen(req: urllib.request.Request, timeout: float) -> tuple[int, bytes, dict]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read() or b"", dict(exc.headers or {})
