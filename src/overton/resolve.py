"""Stage 2: resolve each journal in config/journals.csv to one OpenAlex source id."""
from __future__ import annotations

import difflib
import json

import pandas as pd

from .settings import Paths

NAME_MATCH_THRESHOLD = 0.8
OVERRIDE_COL = "openalex_source_id_override"

RESOLVED_COLUMNS = [
    "journal_key", "journal", "issns", "openalex_source_id", "openalex_display_name",
    "openalex_issn_l", "openalex_issns", "openalex_type", "openalex_works_count",
    "openalex_host_organization", "match_method", "status", "candidates",
]


def short_id(openalex_id: str | None) -> str:
    """`https://openalex.org/S123` -> `S123`."""
    return (openalex_id or "").rsplit("/", 1)[-1]


def name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, (a or "").lower().strip(),
                                   (b or "").lower().strip()).ratio()


def _candidate(src: dict) -> dict:
    return {"id": short_id(src.get("id")), "display_name": src.get("display_name"),
            "issn_l": src.get("issn_l"), "works_count": src.get("works_count"),
            "type": src.get("type")}


def _source_fields(src: dict) -> dict:
    return {
        "openalex_source_id": short_id(src.get("id")),
        "openalex_display_name": src.get("display_name"),
        "openalex_issn_l": src.get("issn_l"),
        "openalex_issns": "; ".join(src.get("issn") or []),
        "openalex_type": src.get("type"),
        "openalex_works_count": src.get("works_count"),
        "openalex_host_organization": src.get("host_organization_name"),
    }


def resolve_row(client, row: dict) -> dict:
    out = {k: "" for k in RESOLVED_COLUMNS}
    out.update(journal_key=row["journal_key"], journal=row["journal"], issns=row["issns"])

    override = str(row.get(OVERRIDE_COL) or "").strip()
    if override and override.lower() != "nan":
        src, _, _ = client.get(f"/sources/{short_id(override)}")
        out.update(_source_fields(src), match_method="override", status="ok")
        return out

    issns = [s.strip() for s in str(row["issns"]).split(";") if s.strip()]
    found: dict[str, dict] = {}
    for issn in issns:
        data, _, _ = client.get("/sources", {"filter": f"issn:{issn}"})
        for src in data.get("results", []):
            found.setdefault(short_id(src["id"]), src)

    if not found:
        data, _, _ = client.get("/sources", {"search": row["journal"]})
        cands = [_candidate(s) for s in data.get("results", [])[:3]]
        out.update(match_method="title_search", status="not_found",
                   candidates=json.dumps(cands, ensure_ascii=False))
        return out

    if len(found) > 1:
        cands = [_candidate(s) for s in found.values()]
        out.update(match_method="issn", status="ambiguous",
                   candidates=json.dumps(cands, ensure_ascii=False))
        return out

    src = next(iter(found.values()))
    out.update(_source_fields(src), match_method="issn")
    sim = name_similarity(row["journal"], src.get("display_name"))
    if src.get("type") != "journal":
        out["status"] = "not_journal"
    elif sim < NAME_MATCH_THRESHOLD:
        out["status"] = "name_mismatch"
    else:
        out["status"] = "ok"
    out["candidates"] = json.dumps([dict(_candidate(src), name_similarity=round(sim, 3))],
                                   ensure_ascii=False)
    return out


def resolve(client, paths: Paths) -> pd.DataFrame:
    journals = pd.read_csv(paths.journals, dtype=str, keep_default_na=False)
    rows = [resolve_row(client, r) for r in journals.to_dict("records")]
    df = pd.DataFrame(rows, columns=RESOLVED_COLUMNS)
    df.to_csv(paths.journals_resolved, index=False, encoding="utf-8")
    return df


def check_resolved(df: pd.DataFrame) -> list[str]:
    """Gate problems for Stage 2 (empty list means the gate passes)."""
    problems = []
    for r in df.to_dict("records"):
        if r["status"] != "ok":
            problems.append(f"{r['journal_key']}: status={r['status']} candidates={r['candidates']}")
    ids = dict(zip(df["journal_key"], df["openalex_source_id"]))
    if ids.get("aer") and ids.get("aer") == ids.get("aea_pp"):
        problems.append(f"aer and aea_pp resolve to the same source id {ids['aer']}")
    dup = df[df["openalex_source_id"].ne("") & df["openalex_source_id"].duplicated(keep=False)]
    for r in dup.to_dict("records"):
        problems.append(f"{r['journal_key']}: source id {r['openalex_source_id']} shared with another journal")
    return problems


def load_resolved(paths: Paths) -> pd.DataFrame:
    return pd.read_csv(paths.journals_resolved, dtype=str, keep_default_na=False)
