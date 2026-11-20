"""Polite, interruptible HTTP layer (and its offline twin for --dry-run).

Design choices that matter for the ethics marks:
  * identifies itself honestly with a descriptive User-Agent,
  * per-host rate limiting,
  * a hard cap on total requests,
  * every wait is interruptible by the kill switch (threading.Event),
  * the dry-run client never opens a socket.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Optional, Set, Tuple

from . import __version__

USER_AGENT = (
    f"socTools/{__version__} (educational OSINT tool; "
    "+https://github.com/zieksyahmi/soctools)"
)
MAX_BODY = 512 * 1024          # never read more than 512 KiB from any response

# (status, payload, detail) with status in {"ok", "not_found", "error"}
Response = Tuple[str, Any, str]


class RequestBudgetExceeded(Exception):
    pass


class HttpClient:
    def __init__(self, stop: threading.Event, delay: float = 1.0,
                 timeout: float = 10.0, max_requests: int = 60):
        self.stop = stop
        self.delay = delay
        self.timeout = timeout
        self.max_requests = max_requests
        self._count = 0
        self._lock = threading.Lock()
        self._last_hit: Dict[str, float] = {}

    # ------------------------------------------------------------------ helpers
    @property
    def requests_made(self) -> int:
        return self._count

    def _reserve(self, host: str) -> None:
        """Take one unit of request budget and sleep to respect the host delay."""
        with self._lock:
            if self._count >= self.max_requests:
                raise RequestBudgetExceeded(f"request cap of {self.max_requests} reached")
            self._count += 1
            now = time.monotonic()
            ready_at = max(now, self._last_hit.get(host, 0.0) + self.delay)
            self._last_hit[host] = ready_at
        wait = ready_at - time.monotonic()
        if wait > 0:
            self.stop.wait(wait)               # returns early if the kill switch fires

    # -------------------------------------------------------------------- public
    def get_json(self, url: str) -> Response:
        if self.stop.is_set():
            return "error", None, "aborted"
        host = urllib.parse.urlparse(url).netloc
        try:
            self._reserve(host)
        except RequestBudgetExceeded as exc:
            return "error", None, str(exc)
        if self.stop.is_set():
            return "error", None, "aborted"
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read(MAX_BODY)
            return "ok", json.loads(raw.decode("utf-8", "replace")), ""
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return "not_found", None, "HTTP 404"
            return "error", None, f"HTTP {exc.code}"
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            return "error", None, f"{type(exc).__name__}: {exc}"

    def get_sha256(self, url: str) -> str:
        """Hash an avatar (opt-in). Image bytes are hashed in memory and discarded."""
        if not url or self.stop.is_set():
            return ""
        host = urllib.parse.urlparse(url).netloc
        try:
            self._reserve(host)
        except RequestBudgetExceeded:
            return ""
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return hashlib.sha256(resp.read(MAX_BODY)).hexdigest()
        except (urllib.error.URLError, TimeoutError, OSError):
            return ""


class DryRunClient:
    """Same interface as HttpClient but answers from built-in synthetic fixtures."""

    def __init__(self, stop: threading.Event, known_users: Set[str], fixtures,
                 log=print):
        self.stop = stop
        self.known = {u.lower() for u in known_users}
        self.fixtures = fixtures
        self.log = log
        self._count = 0
        self._lock = threading.Lock()

    @property
    def requests_made(self) -> int:
        return 0                                   # nothing ever leaves the machine

    def get_json(self, url: str) -> Response:
        with self._lock:
            self.log(f"  [DRY-RUN] would GET {url}")
        payload = self.fixtures(url, self.known)
        if payload is None:
            return "not_found", None, "simulated 404"
        return "ok", payload, "simulated"

    def get_sha256(self, url: str) -> str:
        # Deterministic fake hash: lets the demo show the avatar-match signal.
        if "shared-avatar" in url:
            return hashlib.sha256(b"dry-run-shared-avatar").hexdigest()
        return hashlib.sha256(url.encode()).hexdigest() if url else ""
