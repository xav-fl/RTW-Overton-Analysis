"""Stages 3-4: cursor-page every (journal, year) and store raw pages, with a resumable manifest.

Layout: data/raw/openalex/<journal_key>/<year>/page_0001.json.gz, ... Each page
is the response body exactly as received, gzip-compressed.

The manifest (reports/harvest_manifest.csv) is append-only: every attempt at a
journal-year adds a row, and the latest row for a journal-year is its state.
"""
from __future__ import annotations

import csv
import gzip
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

from . import settings
from .settings import Paths

MANIFEST_COLUMNS = [
    "journal_key", "source_id", "year", "filter", "expected_count", "retrieved_count",
    "unique_work_ids", "n_pages", "locations_count", "status", "started_at",
    "finished_at", "error",
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def works_filter(source_id: str, year: int, field: str = "primary_location.source.id") -> str:
    return f"{field}:{source_id},publication_year:{year}"


def page_path(paths: Paths, journal_key: str, year: int, n: int) -> Path:
    return paths.jy_dir(journal_key, year) / f"page_{n:04d}.json.gz"


def page_files(paths: Paths, journal_key: str, year: int) -> list[Path]:
    d = paths.jy_dir(journal_key, year)
    return sorted(d.glob("page_*.json.gz")) if d.exists() else []


# -- manifest ---------------------------------------------------------------

def read_manifest(paths: Paths) -> list[dict]:
    if not paths.manifest.exists():
        return []
    with paths.manifest.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def latest_manifest(paths: Paths) -> dict[tuple[str, int], dict]:
    """The latest manifest row per (journal_key, year)."""
    out = {}
    for row in read_manifest(paths):
        out[(row["journal_key"], int(row["year"]))] = row
    return out


def append_manifest(paths: Paths, row: dict) -> None:
    paths.manifest.parent.mkdir(parents=True, exist_ok=True)
    new = not paths.manifest.exists()
    with paths.manifest.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in MANIFEST_COLUMNS})


def is_done(paths: Paths, row: dict | None) -> bool:
    """Resume rule: skip a journal-year only if marked complete and its page files exist."""
    if not row or row.get("status") != "complete":
        return False
    files = page_files(paths, row["journal_key"], int(row["year"]))
    return len(files) == int(row["n_pages"] or 0)


# -- one journal-year ---------------------------------------------------------

def _fetch_pages(client, paths: Paths, journal_key: str, source_id: str, year: int) -> dict:
    d = paths.jy_dir(journal_key, year)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    flt = works_filter(source_id, year)
    cursor, n_pages, retrieved, expected = "*", 0, 0, None
    ids: set[str] = set()
    while True:
        data, raw, _ = client.get("/works", {"filter": flt, "per_page": settings.PER_PAGE,
                                             "cursor": cursor})
        if expected is None:
            expected = int(data["meta"]["count"])
        results = data.get("results") or []
        cursor = data["meta"].get("next_cursor")
        if results:
            n_pages += 1
            page_path(paths, journal_key, year, n_pages).write_bytes(gzip.compress(raw))
            retrieved += len(results)
            ids.update(w["id"] for w in results)
        if not cursor or not results:
            break
    return {"expected_count": expected, "retrieved_count": retrieved,
            "unique_work_ids": len(ids), "n_pages": n_pages}


def harvest_journal_year(client, paths: Paths, journal_key: str, source_id: str,
                         year: int, *, with_locations: bool = True) -> dict:
    """Harvest one journal-year from scratch, retrying once on a count mismatch."""
    row = {"journal_key": journal_key, "source_id": source_id, "year": year,
           "filter": works_filter(source_id, year), "started_at": _now()}
    try:
        if with_locations:
            loc, _, _ = client.get("/works", {"filter": works_filter(
                source_id, year, "locations.source.id"), "per_page": 1})
            row["locations_count"] = int(loc["meta"]["count"])
        for attempt in range(2):
            counts = _fetch_pages(client, paths, journal_key, source_id, year)
            row.update(counts)
            ok = (counts["retrieved_count"] == counts["expected_count"]
                  == counts["unique_work_ids"])
            if ok:
                row["status"] = "complete"
                row["error"] = "" if attempt == 0 else "matched on retry"
                break
        else:
            row["status"] = "count_mismatch"
    except Exception as exc:                         # noqa: BLE001 — recorded, then re-raised
        row.update(status="failed", error=str(exc)[:500], finished_at=_now())
        append_manifest(paths, row)
        raise
    row["finished_at"] = _now()
    append_manifest(paths, row)
    return row


def harvest(client, paths: Paths, targets: list[tuple[str, str, int]], *, log=print) -> list[dict]:
    """Harvest each (journal_key, source_id, year) under the resume rule.

    Returns the final manifest row for every target. Does not stop on a
    count_mismatch (that is the caller's gate); does stop on any exception.
    """
    state = latest_manifest(paths)
    out = []
    for jk, sid, year in targets:
        prev = state.get((jk, year))
        if is_done(paths, prev) and prev["source_id"] == sid:
            log(f"  skip {jk} {year}: complete ({prev['retrieved_count']} works)")
            out.append(prev)
            continue
        row = harvest_journal_year(client, paths, jk, sid, year)
        log(f"  {jk} {year}: {row['status']} expected={row['expected_count']} "
            f"retrieved={row['retrieved_count']} pages={row['n_pages']} "
            f"locations={row.get('locations_count', '')}")
        out.append(row)
    return out


# -- request estimate -------------------------------------------------------

def estimate(client, targets: list[tuple[str, str, int]]) -> tuple[int, list[dict]]:
    """Estimated requests = sum(ceil(count/100)) + 2 per journal-year."""
    rows = []
    for jk, sid, year in targets:
        data, _, _ = client.get("/works", {"filter": works_filter(sid, year), "per_page": 1})
        n = int(data["meta"]["count"])
        rows.append({"journal_key": jk, "source_id": sid, "year": year, "count": n,
                     "pages": math.ceil(n / settings.PER_PAGE)})
    total = sum(r["pages"] for r in rows) + 2 * len(rows)
    return total, rows


def read_page(path: Path) -> dict:
    return json.loads(gzip.decompress(path.read_bytes()))
