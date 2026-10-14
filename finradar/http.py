"""Polite HTTP client: per-host throttling, retries with Retry-After, robots.txt,
and explicit detection of anti-bot pages (we stop, we do not try to bypass them)."""

from __future__ import annotations

import logging
import random
import threading
import time
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

log = logging.getLogger(__name__)

DEFAULT_UA = "finradar/0.1 (+personal job-search aggregator; respects robots.txt)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None, url: str | None = None):
        super().__init__(message)
        self.status = status
        self.url = url


class BlockedError(HttpError):
    """The site answered with a captcha / anti-bot page. The source should stop."""


class RobotsDisallowed(HttpError):
    pass


_CAPTCHA_MARKERS = ("captcha", "are you a robot", "проверка, что вы не робот", "cf-challenge", "ddos-guard")


class HttpClient:
    def __init__(
        self,
        user_agent: str = DEFAULT_UA,
        timeout: float = 25.0,
        min_interval: float = 1.0,
        retries: int = 3,
        respect_robots: bool = True,
        host_intervals: dict[str, float] | None = None,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.min_interval = min_interval
        self.retries = retries
        self.respect_robots = respect_robots
        self.host_intervals = host_intervals or {}
        self._session = requests.Session()
        self._lock = threading.Lock()
        self._host_locks: dict[str, threading.Lock] = {}
        self._last_hit: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | None] = {}
        self.stats: dict[str, int] = {"requests": 0, "errors": 0}

    # ------------------------------------------------------------------ helpers
    def _host_lock(self, host: str) -> threading.Lock:
        with self._lock:
            return self._host_locks.setdefault(host, threading.Lock())

    def _throttle(self, host: str, min_interval: float | None) -> None:
        interval = min_interval if min_interval is not None else self.host_intervals.get(host, self.min_interval)
        lock = self._host_lock(host)
        with lock:
            last = self._last_hit.get(host, 0.0)
            wait = last + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait + random.uniform(0, interval * 0.2))
            self._last_hit[host] = time.monotonic()

    def allowed_by_robots(self, url: str, user_agent: str | None = None) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        with self._lock:
            known = base in self._robots
            parser = self._robots.get(base)
        if not known:
            parser = RobotFileParser()
            try:
                resp = self._session.get(f"{base}/robots.txt", timeout=10, headers={"User-Agent": self.user_agent})
                if resp.status_code >= 400:
                    parser = None  # no robots.txt -> everything allowed
                else:
                    parser.parse(resp.text.splitlines())
            except requests.RequestException:
                parser = None
            with self._lock:
                self._robots[base] = parser
        return True if parser is None else parser.can_fetch(user_agent or self.user_agent, url)

    # ------------------------------------------------------------------ requests
    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        headers: dict[str, str] | None = None,
        json_body: Any = None,
        data: Any = None,
        auth: Any = None,
        robots: bool = False,
        min_interval: float | None = None,
        browser_ua: bool = False,
        allow_status: tuple[int, ...] = (),
    ) -> requests.Response:
        if robots and self.respect_robots and not self.allowed_by_robots(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}", url=url)
        host = urlsplit(url).netloc
        hdrs = {"User-Agent": BROWSER_UA if browser_ua else self.user_agent, "Accept-Language": "ru,en;q=0.8"}
        hdrs.update(headers or {})
        last_exc: Exception | None = None
        for attempt in range(1, self.retries + 1):
            self._throttle(host, min_interval)
            try:
                resp = self._session.request(
                    method, url, params=params, headers=hdrs, json=json_body, data=data,
                    auth=auth, timeout=self.timeout,
                )
                self.stats["requests"] += 1
            except requests.RequestException as exc:
                last_exc = exc
                self.stats["errors"] += 1
                time.sleep(min(2**attempt, 20))
                continue
            if resp.status_code in allow_status:
                return resp
            if resp.status_code == 429 or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else min(2**attempt * 2, 60)
                log.info("HTTP %s from %s, retry in %.0fs", resp.status_code, host, delay)
                last_exc = HttpError(f"HTTP {resp.status_code}", resp.status_code, url)
                time.sleep(delay)
                continue
            if self._looks_blocked(resp):
                raise BlockedError(f"anti-bot page at {host} (HTTP {resp.status_code})", resp.status_code, url)
            if resp.status_code >= 400:
                self.stats["errors"] += 1
                raise HttpError(f"HTTP {resp.status_code} for {url}", resp.status_code, url)
            return resp
        self.stats["errors"] += 1
        if isinstance(last_exc, HttpError):
            raise last_exc
        raise HttpError(f"request failed for {url}: {last_exc}", url=url)

    @staticmethod
    def _looks_blocked(resp: requests.Response) -> bool:
        if "captcha" in resp.url.lower():
            return True
        if resp.status_code in (403, 429, 503) or len(resp.content) < 20_000:
            ctype = resp.headers.get("Content-Type", "")
            if "html" in ctype:
                head = resp.text[:5000].lower()
                return any(m in head for m in _CAPTCHA_MARKERS)
        return False

    def get(self, url: str, **kw) -> requests.Response:
        return self.request("GET", url, **kw)

    def get_json(self, url: str, **kw) -> Any:
        headers = {"Accept": "application/json", **kw.pop("headers", {})}
        return self.request("GET", url, headers=headers, **kw).json()

    def get_text(self, url: str, **kw) -> str:
        resp = self.request("GET", url, **kw)
        if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding
        return resp.text

    def post_json(self, url: str, body: Any, **kw) -> Any:
        headers = {"Accept": "application/json", **kw.pop("headers", {})}
        return self.request("POST", url, json_body=body, headers=headers, **kw).json()
