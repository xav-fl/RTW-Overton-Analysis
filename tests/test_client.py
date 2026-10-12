import json

import pytest
import requests

from overton import client as cl
from overton.client import BudgetExhausted, OpenAlexClient, OpenAlexError, redact_url

KEY = "SECRETKEY123"


@pytest.mark.parametrize("url,expected", [
    (f"https://api.openalex.org/works?filter=a:b&api_key={KEY}&per_page=5",
     "https://api.openalex.org/works?filter=a%3Ab&per_page=5"),
    (f"https://api.openalex.org/rate-limit?api_key={KEY}",
     "https://api.openalex.org/rate-limit"),
    (f"https://api.openalex.org/works?API_KEY={KEY}&cursor=*",
     "https://api.openalex.org/works?cursor=%2A"),
    ("https://api.openalex.org/works", "https://api.openalex.org/works"),
])
def test_redact_url(url, expected):
    out = redact_url(url)
    assert KEY not in out
    assert "api_key" not in out.lower()
    assert out == expected


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self.content = json.dumps(body or {}).encode()
        self.text = self.content.decode()


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, timeout):
        self.urls.append(url)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make(responses):
    sleeps = []
    c = OpenAlexClient(KEY, sleep=sleeps.append, session=FakeSession(responses))
    return c, sleeps


def test_success_returns_redacted_url():
    c, _ = make([FakeResponse(200, {"meta": {"count": 1}})])
    data, raw, url = c.get("/works", {"filter": "x:y"})
    assert data["meta"]["count"] == 1
    assert KEY not in url and "api_key" not in url
    assert f"api_key={KEY}" in c._session.urls[0]       # sent as a query parameter


def test_retries_then_succeeds_with_backoff():
    c, sleeps = make([FakeResponse(500), requests.Timeout(), requests.ConnectionError(),
                      FakeResponse(200, {"ok": 1})])
    data, _, _ = c.get("/works")
    assert data == {"ok": 1}
    assert [s for s in sleeps if s >= 1] == [1, 2, 4]


def test_other_4xx_not_retried_and_key_scrubbed():
    c, _ = make([FakeResponse(400, {"error": f"bad key {KEY}"})])
    with pytest.raises(OpenAlexError) as e:
        c.get("/works")
    assert KEY not in str(e.value)
    assert len(c._session.urls) == 1


def test_exhausted_429_is_budget_message():
    c, sleeps = make([FakeResponse(429)] * 6)
    with pytest.raises(BudgetExhausted) as e:
        c.get("/works")
    assert "resume after midnight UTC" in str(e.value)
    assert KEY not in str(e.value)
    assert [s for s in sleeps if s >= 1] == [1, 2, 4, 8, 16]


def test_exhausted_500_is_plain_failure():
    c, _ = make([FakeResponse(503)] * 6)
    with pytest.raises(OpenAlexError) as e:
        c.get("/works")
    assert not isinstance(e.value, BudgetExhausted)


def test_missing_key(monkeypatch):
    monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
    with pytest.raises(cl.KeyMissing):
        OpenAlexClient()


def test_fixtures_contain_no_key_parameter():
    from pathlib import Path
    for f in (Path(__file__).parent / "fixtures").glob("*.json"):
        assert "api_key" not in f.read_text(encoding="utf-8")
