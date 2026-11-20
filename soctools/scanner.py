"""Concurrent scan engine with a cooperative kill switch."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional

from .models import LookupResult
from .platforms import Platform


class Scanner:
    """Looks up every (platform, username) pair and keeps results as they arrive.

    ``results`` is filled incrementally, so if the operator presses Ctrl+C the
    caller still holds everything gathered so far (partial-progress saving).
    """

    def __init__(self, client, platforms: List[Platform], usernames: List[str],
                 stop: threading.Event, workers: int = 4, avatar_hash: bool = False,
                 on_result: Optional[Callable[[LookupResult], None]] = None):
        self.client = client
        self.platforms = platforms
        self.usernames = usernames
        self.stop = stop
        self.workers = max(1, workers)
        self.avatar_hash = avatar_hash
        self.on_result = on_result
        self.results: List[LookupResult] = []
        self.interrupted = False
        self._lock = threading.Lock()

    def _lookup(self, platform: Platform, username: str) -> LookupResult:
        if self.stop.is_set():
            return LookupResult(platform.name, username, "skipped", detail="aborted")
        status, data, detail = self.client.get_json(platform.api_url(username))
        if status == "not_found":
            return LookupResult(platform.name, username, "not_found", detail=detail)
        if status != "ok":
            kind = "skipped" if detail == "aborted" else "error"
            return LookupResult(platform.name, username, kind, detail=detail)
        profile = platform.parse(username, data)
        if profile is None:
            return LookupResult(platform.name, username, "not_found", detail="empty payload")
        if self.avatar_hash and profile.avatar_url:
            profile.avatar_hash = self.client.get_sha256(profile.avatar_url)
        return LookupResult(platform.name, username, "found", profile, detail)

    def _record(self, result: LookupResult) -> None:
        with self._lock:
            self.results.append(result)
        if self.on_result:
            self.on_result(result)

    def run(self) -> List[LookupResult]:
        tasks = [(p, u) for u in self.usernames for p in self.platforms]
        pool = ThreadPoolExecutor(max_workers=self.workers)
        futures = [pool.submit(self._lookup, p, u) for p, u in tasks]
        try:
            for fut in as_completed(futures):
                self._record(fut.result())
        except KeyboardInterrupt:
            # Kill switch: tell workers to stop, drop queued work, keep what we have.
            self.interrupted = True
            self.stop.set()
            pool.shutdown(wait=True, cancel_futures=True)
            for fut in futures:                       # harvest tasks that finished anyway
                if fut.done() and not fut.cancelled():
                    res = fut.result()
                    if res not in self.results and res.status != "skipped":
                        self._record(res)
        else:
            pool.shutdown(wait=True)
        return self.results
