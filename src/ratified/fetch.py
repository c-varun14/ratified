"""Cache-first HTTP GET with retry, exponential backoff and rate-limit throttling.

mailarchive sits behind Cloudflare and answers bursts with HTTP 429 (error 1015),
sometimes carrying a large Retry-After. Responses are cached on disk keyed by the
SHA-256 of the URL, so a warmed cache replays the whole pull with no network. When
RATIFIED_OFFLINE=1 a cache miss raises instead of touching the network.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import os
import random
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .paths import CACHE_DIR

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
OFFLINE_ENV = "RATIFIED_OFFLINE"
DEFAULT_CACHE_DIR = CACHE_DIR
_RETRYABLE = (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError)


class Fetcher:
    def __init__(
        self,
        cache_dir: str | None = None,
        max_retries: int = 6,
        base_delay: float = 1.0,
        timeout: float = 45.0,
        min_interval: float = 0.7,
        max_interval: float = 20.0,
        offline: bool | None = None,
        opener=None,
        sleep=None,
    ):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = timeout
        self.min_interval = min_interval
        self.max_interval = max_interval
        self._offline = offline
        self._opener = opener or _urlopen
        self._sleep = sleep or time.sleep
        self._lock = threading.Lock()
        self._next_allowed = 0.0
        os.makedirs(self.cache_dir, exist_ok=True)
        self.stats = {
            "requests": 0,
            "cache_hits": 0,
            "network_fetches": 0,
            "retries": 0,
            "attempts_total": 0,
            "http_error_codes": {},
            "rate_limited_429": 0,
            "failures": [],
        }

    def get(self, url: str, use_cache: bool = True) -> bytes:
        body_path, meta_path = self._paths(url)
        with self._lock:
            self.stats["requests"] += 1
        if use_cache and self._cacheable(body_path, meta_path):
            with self._lock:
                self.stats["cache_hits"] += 1
            return Path(body_path).read_bytes()
        if self.offline:
            self._failure(url, "offline-cache-miss", 0)
            raise RuntimeError(f"offline: not cached: {url}")

        last_err = None
        started = time.time()
        for attempt in range(self.max_retries + 1):
            with self._lock:
                self.stats["attempts_total"] += 1
                if attempt:
                    self.stats["retries"] += 1
            try:
                self._throttle()
                request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
                data, content_type, status = self._opener(request, self.timeout)
                self._store(url, body_path, meta_path, data, content_type, status, attempt + 1, started)
                with self._lock:
                    self.stats["network_fetches"] += 1
                return data
            except urllib.error.HTTPError as exc:
                last_err = f"HTTP {exc.code}"
                with self._lock:
                    self.stats["http_error_codes"][str(exc.code)] = (
                        self.stats["http_error_codes"].get(str(exc.code), 0) + 1
                    )
                if exc.code == 429:
                    with self._lock:
                        self.stats["rate_limited_429"] += 1
                        self.min_interval = min(max(self.min_interval * 2, 2.0), self.max_interval)
                    self._sleep(self._rate_limit_pause(exc, attempt))
                    continue
                if exc.code in (404, 410):
                    break
            except _RETRYABLE as exc:
                last_err = f"{type(exc).__name__}: {exc}"
            self._sleep(min(self.base_delay * (2**attempt) + random.uniform(0, 0.5), 30.0))
        self._failure(url, last_err, self.max_retries + 1)
        raise RuntimeError(f"fetch failed after {self.max_retries + 1} attempts: {url} ({last_err})")

    @property
    def offline(self) -> bool:
        if self._offline is not None:
            return self._offline
        return os.environ.get(OFFLINE_ENV) == "1"

    def cache_age(self, url: str) -> float | None:
        """Seconds since the cached response was stored, or None if not cached."""
        body_path, meta_path = self._paths(url)
        if not self._cacheable(body_path, meta_path):
            return None
        try:
            stored = float(json.loads(Path(meta_path).read_text()).get("ts", 0))
        except (ValueError, OSError):
            return None
        return max(0.0, time.time() - stored)

    def save_stats(self, path: str | None = None) -> str:
        path = path or os.path.join(os.path.dirname(self.cache_dir.rstrip("/")), "fetch_stats.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with self._lock:
            snapshot = json.loads(json.dumps(self.stats))
        Path(path).write_text(json.dumps(snapshot, indent=2))
        return path

    def _rate_limit_pause(self, exc: urllib.error.HTTPError, attempt: int) -> float:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        return max(_retry_after_seconds(retry_after), min(5.0 * (attempt + 1), 60.0))

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = max(0.0, self._next_allowed - now)
            self._next_allowed = max(now, self._next_allowed) + self.min_interval
        if wait > 0:
            self._sleep(wait)

    def _paths(self, url: str) -> tuple[str, str]:
        key = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return (
            os.path.join(self.cache_dir, key + ".body"),
            os.path.join(self.cache_dir, key + ".meta.json"),
        )

    def _cacheable(self, body_path: str, meta_path: str) -> bool:
        if not (os.path.exists(body_path) and os.path.exists(meta_path)):
            return False
        try:
            status = int(json.loads(Path(meta_path).read_text()).get("status", 0))
        except (ValueError, OSError):
            return False
        return 200 <= status < 300

    def _store(self, url, body_path, meta_path, data, content_type, status, attempts, started) -> None:
        temporary = f"{body_path}.tmp{os.getpid()}"
        Path(temporary).write_bytes(data)
        os.replace(temporary, body_path)
        Path(meta_path).write_text(
            json.dumps(
                {
                    "url": url,
                    "status": status,
                    "content_type": content_type,
                    "bytes": len(data),
                    "elapsed_s": round(time.time() - started, 3),
                    "attempts": attempts,
                    "ts": time.time(),
                }
            )
        )

    def _failure(self, url: str, error, attempts: int) -> None:
        with self._lock:
            self.stats["failures"].append({"url": url, "error": error, "attempts": attempts})


def _urlopen(request, timeout):
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", ""), getattr(response, "status", 200)


def _retry_after_seconds(header: str | None) -> float:
    if not header:
        return 0.0
    try:
        return max(0.0, float(header))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(header)
        return max(0.0, when.timestamp() - time.time())
    except (TypeError, ValueError):
        return 0.0
