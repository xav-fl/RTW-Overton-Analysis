import json

import pytest

from overton import harvest
from overton.settings import Paths


class FakeClient:
    """Serves `n` works per journal-year in pages of `per_page`, via cursors."""

    def __init__(self, counts, per_page=100, drop=None):
        self.counts = counts            # {(source_id, year): n}
        self.per_page = per_page
        self.drop = drop or {}          # {(source_id, year): n works silently missing}
        self.calls = []

    def get(self, path, params=None):
        params = params or {}
        self.calls.append(params)
        parts = dict(p.split(":", 1) for p in params["filter"].split(","))
        sid = parts.get("primary_location.source.id") or parts["locations.source.id"]
        year = int(parts["publication_year"])
        n = self.counts[(sid, year)]
        if params.get("per_page") == 1:
            body = {"meta": {"count": n, "next_cursor": None}, "results": []}
        else:
            start = 0 if params["cursor"] == "*" else int(params["cursor"])
            available = n - self.drop.get((sid, year), 0)
            results = [{"id": f"https://openalex.org/W{sid}{year}{i}"}
                       for i in range(start, min(start + self.per_page, available))]
            nxt = str(start + self.per_page) if results else None
            body = {"meta": {"count": n, "next_cursor": nxt}, "results": results}
        raw = json.dumps(body).encode()
        return body, raw, "redacted"


def jy_requests(client, sid, year):
    return [c for c in client.calls
            if f"{sid},publication_year:{year}" in c["filter"]]


def test_harvest_pages_and_manifest(tmp_path):
    paths = Paths(tmp_path)
    c = FakeClient({("S1", 2020): 250})
    rows = harvest.harvest(c, paths, [("aer", "S1", 2020)], log=lambda *a: None)
    r = rows[0]
    assert r["status"] == "complete"
    assert (r["expected_count"], r["retrieved_count"], r["unique_work_ids"], r["n_pages"]) == (250, 250, 250, 3)
    assert r["locations_count"] == 250
    files = harvest.page_files(paths, "aer", 2020)
    assert [f.name for f in files] == ["page_0001.json.gz", "page_0002.json.gz", "page_0003.json.gz"]
    assert len(harvest.read_page(files[0])["results"]) == 100
    m = harvest.read_manifest(paths)
    assert len(m) == 1 and m[0]["status"] == "complete"
    assert "api_key" not in paths.manifest.read_text()


def test_zero_count_is_complete(tmp_path):
    paths = Paths(tmp_path)
    c = FakeClient({("S9", 2016): 0})
    r = harvest.harvest(c, paths, [("aea_pp", "S9", 2016)], log=lambda *a: None)[0]
    assert r["status"] == "complete" and r["n_pages"] == 0
    assert harvest.is_done(paths, harvest.latest_manifest(paths)[("aea_pp", 2016)])


def test_resume_skips_complete_and_redoes_incomplete(tmp_path):
    paths = Paths(tmp_path)
    targets = [("aer", "S1", 2019), ("aer", "S1", 2020)]
    first = FakeClient({("S1", 2019): 150, ("S1", 2020): 150}, drop={("S1", 2020): 10})
    rows = harvest.harvest(first, paths, targets, log=lambda *a: None)
    assert [r["status"] for r in rows] == ["complete", "count_mismatch"]
    # mismatch retried once from scratch: two full walks for 2020
    walks_2020 = [c for c in jy_requests(first, "S1", 2020) if c.get("cursor") == "*"]
    assert len(walks_2020) == 2

    # leave a stale extra page behind for the incomplete year
    stale = harvest.page_path(paths, "aer", 2020, 9)
    stale.write_bytes(b"junk")

    second = FakeClient({("S1", 2019): 150, ("S1", 2020): 150})
    rows = harvest.harvest(second, paths, targets, log=lambda *a: None)
    assert [r["status"] for r in rows] == ["complete", "complete"]
    assert jy_requests(second, "S1", 2019) == []           # complete year skipped
    assert not stale.exists()                              # incomplete year cleared
    assert len(harvest.page_files(paths, "aer", 2020)) == 2
    latest = harvest.latest_manifest(paths)
    assert latest[("aer", 2020)]["status"] == "complete"
    assert len(harvest.read_manifest(paths)) == 3          # append-only log


def test_complete_but_missing_files_is_redone(tmp_path):
    paths = Paths(tmp_path)
    c = FakeClient({("S1", 2020): 120})
    harvest.harvest(c, paths, [("aer", "S1", 2020)], log=lambda *a: None)
    harvest.page_files(paths, "aer", 2020)[1].unlink()
    c2 = FakeClient({("S1", 2020): 120})
    harvest.harvest(c2, paths, [("aer", "S1", 2020)], log=lambda *a: None)
    assert jy_requests(c2, "S1", 2020)                     # redone
    assert len(harvest.page_files(paths, "aer", 2020)) == 2


def test_failure_recorded_and_raised(tmp_path):
    paths = Paths(tmp_path)

    class Boom(FakeClient):
        def get(self, path, params=None):
            raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        harvest.harvest(Boom({}), paths, [("aer", "S1", 2020)], log=lambda *a: None)
    assert harvest.latest_manifest(paths)[("aer", 2020)]["status"] == "failed"


def test_estimate():
    c = FakeClient({("S1", 2019): 250, ("S1", 2020): 0})
    total, rows = harvest.estimate(c, [("aer", "S1", 2019), ("aer", "S1", 2020)])
    assert total == 3 + 0 + 2 * 2
