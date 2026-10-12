"""Stage 5: raw pages -> data/interim/works.csv and authorships.csv (no network)."""
from __future__ import annotations

import re

import pandas as pd

from . import harvest
from .settings import Paths

WORK_COLUMNS = [
    "openalex_id", "doi", "title", "publication_year", "publication_date", "journal_key",
    "source_id", "source_display_name", "volume", "issue", "first_page", "last_page",
    "page_count", "openalex_type", "is_paratext", "is_retracted", "language", "abstract",
    "has_abstract", "abstract_word_count", "abstract_mentions_jel", "n_authors",
    "n_institutions", "n_countries", "cited_by_count", "fwci", "referenced_works_count",
    "primary_topic", "primary_subfield", "primary_field", "primary_domain", "keywords",
    "is_oa", "oa_status", "harvest_date", "raw_file",
]

AUTHORSHIP_COLUMNS = [
    "openalex_id", "author_order", "author_position", "author_id", "author_name", "orcid",
    "is_corresponding", "institution_id", "institution_name", "institution_ror",
    "institution_country", "institution_type", "raw_affiliation_strings",
]

_DOI_PREFIX = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/", re.IGNORECASE)
_JEL = re.compile(r"\bJEL\b")
_INT = re.compile(r"^\d+$")


def reconstruct_abstract(index: dict | None) -> str:
    """Place each word at each of its positions, order by position, join with spaces."""
    if not index:
        return ""
    placed = [(pos, word) for word, positions in index.items() for pos in (positions or [])]
    placed.sort(key=lambda t: t[0])
    return " ".join(w for _, w in placed).strip()


def normalise_doi(doi: str | None) -> str | None:
    if doi is None:
        return None
    doi = doi.strip()
    if not doi:
        return None
    return _DOI_PREFIX.sub("", doi).lower()


def page_count(first, last):
    f, l = str(first or "").strip(), str(last or "").strip()
    if _INT.match(f) and _INT.match(l):
        return int(l) - int(f) + 1
    return None


def _get(obj, *keys):
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def work_row(w: dict, journal_key: str, harvest_date: str, raw_file: str) -> dict:
    abstract = reconstruct_abstract(w.get("abstract_inverted_index"))
    biblio = w.get("biblio") or {}
    auths = w.get("authorships") or []
    insts = {i.get("id") for a in auths for i in (a.get("institutions") or []) if i.get("id")}
    countries = {c for a in auths for c in (a.get("countries") or []) if c}
    topic = w.get("primary_topic") or {}
    oa = w.get("open_access") or {}
    return {
        "openalex_id": w.get("id"),
        "doi": normalise_doi(w.get("doi")),
        "title": w.get("title"),
        "publication_year": w.get("publication_year"),
        "publication_date": w.get("publication_date"),
        "journal_key": journal_key,
        "source_id": _get(w, "primary_location", "source", "id"),
        "source_display_name": _get(w, "primary_location", "source", "display_name"),
        "volume": biblio.get("volume"),
        "issue": biblio.get("issue"),
        "first_page": biblio.get("first_page"),
        "last_page": biblio.get("last_page"),
        "page_count": page_count(biblio.get("first_page"), biblio.get("last_page")),
        "openalex_type": w.get("type"),
        "is_paratext": w.get("is_paratext"),
        "is_retracted": w.get("is_retracted"),
        "language": w.get("language"),
        "abstract": abstract,
        "has_abstract": bool(abstract),
        "abstract_word_count": len(abstract.split()),
        "abstract_mentions_jel": bool(_JEL.search(abstract)),
        "n_authors": len(auths),
        "n_institutions": len(insts),
        "n_countries": len(countries),
        "cited_by_count": w.get("cited_by_count"),
        "fwci": w.get("fwci"),
        "referenced_works_count": w.get("referenced_works_count"),
        "primary_topic": topic.get("display_name"),
        "primary_subfield": _get(topic, "subfield", "display_name"),
        "primary_field": _get(topic, "field", "display_name"),
        "primary_domain": _get(topic, "domain", "display_name"),
        "keywords": "; ".join(k.get("display_name") or "" for k in (w.get("keywords") or [])),
        "is_oa": oa.get("is_oa"),
        "oa_status": oa.get("oa_status"),
        "harvest_date": harvest_date,
        "raw_file": raw_file,
    }


def authorship_rows(w: dict) -> list[dict]:
    rows = []
    for order, a in enumerate(w.get("authorships") or [], start=1):
        author = a.get("author") or {}
        base = {
            "openalex_id": w.get("id"),
            "author_order": order,
            "author_position": a.get("author_position"),
            "author_id": author.get("id"),
            "author_name": author.get("display_name"),
            "orcid": author.get("orcid"),
            "is_corresponding": a.get("is_corresponding"),
            "raw_affiliation_strings": "; ".join(a.get("raw_affiliation_strings") or []),
        }
        insts = a.get("institutions") or []
        if not insts:
            rows.append(dict(base, institution_id=None, institution_name=None,
                             institution_ror=None, institution_country=None,
                             institution_type=None))
        for i in insts:
            rows.append(dict(base, institution_id=i.get("id"),
                             institution_name=i.get("display_name"),
                             institution_ror=i.get("ror"),
                             institution_country=i.get("country_code"),
                             institution_type=i.get("type")))
    return [{c: r[c] for c in AUTHORSHIP_COLUMNS} for r in rows]


def normalise(paths: Paths) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Read every complete journal-year's pages. Returns (works, authorships, gate problems)."""
    state = harvest.latest_manifest(paths)
    works, auths, problems = [], [], []
    expected_total = 0
    for (jk, year), row in sorted(state.items()):
        if row["status"] != "complete":
            problems.append(f"{jk} {year}: manifest status {row['status']}")
            continue
        expected_total += int(row["retrieved_count"])
        harvest_date = (row["finished_at"] or "")[:10]
        for f in harvest.page_files(paths, jk, year):
            rel = f.relative_to(paths.root).as_posix()
            for w in harvest.read_page(f).get("results") or []:
                works.append(work_row(w, jk, harvest_date, rel))
                auths.extend(authorship_rows(w))
    wdf = pd.DataFrame(works, columns=WORK_COLUMNS)
    adf = pd.DataFrame(auths, columns=AUTHORSHIP_COLUMNS)
    for col in ("page_count",):
        wdf[col] = wdf[col].astype("Int64")
    if len(wdf) != expected_total:
        problems.append(f"works.csv has {len(wdf)} rows; manifest retrieved_count sums to {expected_total}")
    dup = wdf["openalex_id"][wdf["openalex_id"].duplicated()]
    if len(dup):
        problems.append(f"{len(dup)} duplicate openalex_id values, e.g. {list(dup[:5])}")
    paths.interim.mkdir(parents=True, exist_ok=True)
    wdf.to_csv(paths.works, index=False, encoding="utf-8")
    adf.to_csv(paths.authorships, index=False, encoding="utf-8")
    return wdf, adf, problems


def load_works(paths: Paths, filtered: bool = False) -> pd.DataFrame:
    df = pd.read_csv(paths.works_filtered if filtered else paths.works,
                     dtype={"doi": str, "volume": str, "issue": str, "first_page": str,
                            "last_page": str, "title": str, "abstract": str,
                            "review_flags": str, "exclusion_reason": str},
                     keep_default_na=False, na_values=[""], encoding="utf-8",
                     low_memory=False)
    for c in ("doi", "title", "abstract", "review_flags", "exclusion_reason"):
        if c in df:
            df[c] = df[c].fillna("")
    df["page_count"] = df["page_count"].astype("Int64")
    return df
