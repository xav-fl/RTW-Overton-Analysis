"""HTTP access to OpenAlex: api_key handling, redaction, retry/backoff, rate limit.

The key is read from the environment and sent only as a query parameter. It
never appears in anything this module returns: every URL handed back (for
logs, manifests, fixtures, error messages) goes through `redact_url` first.
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
from typing import Optional

import requests

from . import settings


class OpenAlexError(RuntimeError):
    """A request failed and will not be retried."""


class BudgetExhausted(OpenAlexError):
    """Retries on 429/403 ran out: the daily budget or rate limit is spent."""

    def __init__(self, detail: str = ""):
        super().__init__(settings.BUDGET_MESSAGE + (f" ({detail})" if detail else ""))


class KeyMissing(OpenAlexError):
    pass


def redact_url(url: str) -> str:
    """Remove every `api_key` query parameter from a URL, keeping the rest intact."""
    parts = urllib.parse.urlsplit(url)
    if not parts.query:
        return url
    kept = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
            if k.lower() != "api_key"]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(kept)))


def _should_retry(status: int) -> bool:
    return status in settings.RETRY_STATUSES or status >= 500


class OpenAlexClient:
    """`get(path, params) -> (data, raw_bytes, redacted_url)`.

    Retries up to len(BACKOFF) times on 429, 403, >=500, timeouts and dropped
    connections. Any other 4xx fails immediately. Requests are spaced so that
    no more than MAX_REQUESTS_PER_SECOND are sent.
    """

    def __init__(self, api_key: Optional[str] = None, *, sleep=time.sleep,
                 session: Optional[requests.Session] = None):
        self._key = api_key if api_key is not None else os.environ.get(settings.API_KEY_ENV)
        if not self._key:
            raise KeyMissing(f"{settings.API_KEY_ENV} is not set")
        self._session = session or requests.Session()
        self._sleep = sleep
        self._min_interval = 1.0 / settings.MAX_REQUESTS_PER_SECOND
        self._last_sent = 0.0
        self.calls = 0          # successful requests
        self.attempts = 0       # every request sent, retries included

    def _scrub(self, text: str) -> str:
        return text.replace(self._key, "<redacted>") if self._key else text

    def _pace(self) -> None:
        wait = self._last_sent + self._min_interval - time.monotonic()
        if wait > 0:
            self._sleep(wait)
        self._last_sent = time.monotonic()

    def get(self, path: str, params: Optional[dict] = None):
        query = dict(params or {})
        query["api_key"] = self._key
        url = settings.API_BASE + path + "?" + urllib.parse.urlencode(query)
        safe = redact_url(url)
        last_problem = ""
        throttled = False
        for attempt in range(len(settings.BACKOFF) + 1):
            if attempt:
                self._sleep(settings.BACKOFF[attempt - 1])
            self._pace()
            self.attempts += 1
            try:
                r = self._session.get(url, timeout=settings.TIMEOUT)
            except (requests.Timeout, requests.ConnectionError) as exc:
                throttled = False
                last_problem = type(exc).__name__
                continue
            if r.status_code == 200:
                self.calls += 1
                raw = r.content
                return json.loads(raw), raw, safe
            if _should_retry(r.status_code):
                throttled = r.status_code in settings.RETRY_STATUSES
                last_problem = f"HTTP {r.status_code}"
                continue
            raise OpenAlexError(f"HTTP {r.status_code} for {safe}: "
                                f"{self._scrub(r.text[:300])}")
        if throttled:
            raise BudgetExhausted(f"{last_problem} for {safe}")
        raise OpenAlexError(f"{last_problem} after {len(settings.BACKOFF)} retries for {safe}")

    def rate_limit(self) -> dict:
        """The `rate_limit` block of /rate-limit (the echoed, masked key is dropped)."""
        data, _, _ = self.get("/rate-limit")
        return dict(data.get("rate_limit") or {})


def log_usage(paths: settings.Paths, command: str, client: OpenAlexClient,
              before: dict, after: dict) -> None:
    """Append one line per networked command to data/interim/api_usage.jsonl."""
    paths.interim.mkdir(parents=True, exist_ok=True)
    rec = {
        "command": command,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "requests": client.calls,
        "attempts": client.attempts,
        "usd_used_before": before.get("daily_used_usd"),
        "usd_used_after": after.get("daily_used_usd"),
        "usd_remaining_after": after.get("daily_remaining_usd"),
        "resets_at": after.get("resets_at"),
    }
    with paths.api_usage.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec) + "\n")
