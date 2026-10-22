"""Stage 3: policy citations from Overton exports (no network).

Input: Overton's "policy documents" exports (one row per citing document, with
every DOI it cites in "Cited DOIs"), saved as CSV in data/raw/overton/, plus
a copy of each DOI list that was searched, in data/raw/overton/queried/, so a
paper that was searched and not cited gets 0 and one never searched stays blank.

Which citing documents count (decided 2026-10-22):
- government, IGO and legislative sources: everything, including their
  research working papers;
- think tanks and NGOs: everything except working papers, which removes the
  academic series Overton files as think tanks (NBER, IZA discussion papers,
  ifo/CESifo, IFS working papers) while keeping their policy reports;
- scholarly articles: never.
`policy_cites_all` counts every document Overton returned, for comparison.

A citing document is counted once per paper even when Overton lists it more
than once (same title under one source, or one paper issued by two
institutions): documents are de-duplicated on normalised title.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .normalise import normalise_doi
from .settings import Paths

PUBLIC_TYPES = frozenset({"Government", "IGO", "Legislative Body"})
NON_PUBLIC_TYPES = frozenset({"Think Tank", "NGO"})
NEVER_TYPES = frozenset({"Scholarly article"})

#: Source countries counted as Europe (Overton uses "EU" for EU bodies).
EUROPE = frozenset({
    "EU", "UK", "Germany", "France", "Italy", "Spain", "Netherlands", "Belgium",
    "Luxembourg", "Ireland", "Sweden", "Finland", "Denmark", "Norway", "Iceland",
    "Switzerland", "Austria", "Portugal", "Greece", "Poland", "Czech Republic",
    "Slovakia", "Slovenia", "Hungary", "Estonia", "Latvia", "Lithuania", "Croatia",
    "Romania", "Bulgaria", "Malta", "Cyprus",
})

#: Runs of anything but letters and digits, in any script (Korean titles must not reduce to "").
_TITLE = re.compile(r"[\W_]+")


def region(country: str) -> str:
    if country == "USA":
        return "us"
    if country == "IGO":
        return "international"
    if country in EUROPE:
        return "europe"
    return "other"


def doc_rule(org_type: str, doc_type: str) -> tuple[bool, str]:
    """(counts as a policy citation, reason)."""
    if doc_type in NEVER_TYPES:
        return False, "scholarly article"
    if org_type in PUBLIC_TYPES:
        return True, "public source"
    if doc_type == "Working paper":
        return False, "working paper from a non-public source"
    return True, "non-public source, not a working paper"


def load_exports(paths: Paths) -> pd.DataFrame:
    files = sorted(paths.overton_raw.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"no Overton exports (*.csv) in {paths.overton_raw}")
    frames = [pd.read_csv(f, low_memory=False).assign(export_file=f.name) for f in files]
    d = pd.concat(frames, ignore_index=True)
    # The same document can appear in two exports (overlapping DOI batches).
    return d.drop_duplicates("Overton document ID").reset_index(drop=True)


def queried_dois(paths: Paths) -> set[str]:
    """DOIs actually searched in Overton: the lists saved in data/raw/overton/queried/."""
    files = sorted(paths.overton_queried.glob("*.txt"))
    if not files:
        raise FileNotFoundError(f"no searched-DOI lists (*.txt) in {paths.overton_queried}")
    out: set[str] = set()
    for f in files:
        out |= {normalise_doi(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()}
    return out


def citation_links(docs: pd.DataFrame, dois: set[str]) -> pd.DataFrame:
    """One row per (paper DOI, citing document), with the inclusion rule applied."""
    rows = []
    for r in docs.to_dict("records"):
        cited = {normalise_doi(x) for x in str(r.get("Cited DOIs") or "").split(";") if x.strip()}
        ok, why = doc_rule(r["Source organisation type"], r["Document type"])
        year = str(r.get("Publication date") or "")[:4]
        for doi in sorted(cited & dois):
            rows.append({
                "doi": doi,
                "overton_document_id": r["Overton document ID"],
                "document_title": r["Document title"],
                "title_key": (_TITLE.sub(" ", str(r["Document title"] or "").casefold()).strip()
                              or r["Overton document ID"]),
                "document_type": r["Document type"],
                "document_series": r.get("Document series"),
                "citing_year": int(year) if year.isdigit() else None,
                "source_id": r["Overton source ID"],
                "source_name": r["Source name"],
                "source_type": r["Source organisation type"],
                "source_country": r["Source country"],
                "source_region": region(r["Source country"]),
                "counts": ok,
                "rule": why,
                "overton_url": r.get("Overton URL"),
            })
    links = pd.DataFrame(rows)
    # Count a document once per paper: later rows with the same paper and title are duplicates.
    links["duplicate"] = links.duplicated(["doi", "title_key"])
    return links


def paper_counts(links: pd.DataFrame, papers: pd.DataFrame, queried: set[str]) -> pd.DataFrame:
    """Per-paper citation measures. Papers whose DOI was not searched get blanks."""
    use = links[~links["duplicate"]]
    main = use[use["counts"]]
    pub = papers.set_index("doi")["publication_year"]
    rows = []
    for doi in papers["doi"].dropna():
        if doi not in queried:
            rows.append({"doi": doi, "overton_queried": False})
            continue
        m, a = main[main["doi"] == doi], use[use["doi"] == doi]
        years = m["citing_year"].dropna()
        first = int(years.min()) if len(years) else None
        row = {
            "doi": doi, "overton_queried": True,
            "policy_cites": len(m),
            "policy_cited_any": len(m) > 0,
            "policy_cites_all": len(a),
            "policy_cites_excluded": len(a) - len(m),
            "policy_cites_government": int((m["source_type"] == "Government").sum()),
            "policy_cites_igo": int((m["source_type"] == "IGO").sum()),
            "policy_cites_legislative": int((m["source_type"] == "Legislative Body").sum()),
            "policy_cites_think_tank_ngo": int(m["source_type"].isin(NON_PUBLIC_TYPES).sum()),
            "policy_cites_us": int((m["source_region"] == "us").sum()),
            "policy_cites_europe": int((m["source_region"] == "europe").sum()),
            "policy_cites_international": int((m["source_region"] == "international").sum()),
            "policy_cites_other_region": int((m["source_region"] == "other").sum()),
            "policy_cites_n_sources": int(m["source_id"].nunique()),
            "policy_first_cite_year": first,
            "policy_years_to_first_cite": (first - int(pub[doi]) if first is not None else None),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def source_table(links: pd.DataFrame) -> pd.DataFrame:
    """One row per citing source: how many of its documents count and why, for review."""
    use = links[~links["duplicate"]]
    g = use.groupby(["source_id", "source_name", "source_type", "source_country"])
    out = g.agg(documents=("counts", "size"), counted=("counts", "sum"),
                working_papers=("document_type", lambda s: int((s == "Working paper").sum())))
    out["excluded"] = out["documents"] - out["counted"]
    return out.reset_index().sort_values(["excluded", "documents"], ascending=False)


def merge(paths: Paths, coded: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(papers with citation columns, citation links, source table); writes all three."""
    docs = load_exports(paths)
    queried = queried_dois(paths)
    links = citation_links(docs, queried)
    counts = paper_counts(links, coded[["doi", "publication_year"]], queried)
    out = coded.merge(counts, on="doi", how="left", validate="many_to_one")
    sources = source_table(links)
    paths.release.mkdir(parents=True, exist_ok=True)
    out.to_csv(paths.papers_cited, index=False, encoding="utf-8")
    links.to_csv(paths.citation_links, index=False, encoding="utf-8")
    sources.to_csv(paths.overton_sources, index=False, encoding="utf-8")
    return out, links, sources
