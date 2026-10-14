from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import pytest

from finradar.http import HttpClient, HttpError


class FakeResponse:
    def __init__(self, payload: Any, url: str, status: int = 200, content_type: str | None = None):
        if isinstance(payload, (dict, list)):
            body = json.dumps(payload, ensure_ascii=False).encode()
            content_type = content_type or "application/json"
        elif isinstance(payload, bytes):
            body = payload
        else:
            body = str(payload).encode()
        self.content = body
        self.status_code = status
        self.url = url
        self.headers = {"Content-Type": content_type or "text/html; charset=utf-8"}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8")

    def json(self) -> Any:
        return json.loads(self.content)


Route = tuple[str, Any]


class FakeHttp(HttpClient):
    """HttpClient that answers from an in-memory routing table instead of the network.

    Each route is (regex matched against "METHOD url?query", payload). A payload may be a
    callable(url, params, body) returning the payload, or an int status code for errors.
    """

    def __init__(self, routes: list[Route] | None = None):
        super().__init__(min_interval=0, respect_robots=False)
        self.routes: list[tuple[re.Pattern, Any]] = [(re.compile(p), v) for p, v in (routes or [])]
        self.calls: list[tuple[str, str, Any, Any]] = []

    def add(self, pattern: str, payload: Any) -> None:
        self.routes.insert(0, (re.compile(pattern), payload))

    def request(self, method, url, *, params=None, headers=None, json_body=None, data=None, auth=None,
                robots=False, min_interval=None, browser_ua=False, allow_status=()):
        query = ""
        if params:
            items = params.items() if isinstance(params, dict) else params
            query = "&".join(f"{k}={v}" for k, v in items if v is not None)
        key = f"{method} {url}" + (f"?{query}" if query else "")
        self.calls.append((method, url, params, json_body))
        for rx, payload in self.routes:
            if rx.search(key):
                if callable(payload):
                    payload = payload(url, params, json_body)
                if isinstance(payload, int):
                    raise HttpError(f"HTTP {payload}", payload, url)
                return FakeResponse(payload, url)
        raise HttpError(f"HTTP 404 (no fake route) for {key}", 404, url)


@pytest.fixture
def fake_http() -> Callable[..., FakeHttp]:
    return lambda routes=None: FakeHttp(routes)
