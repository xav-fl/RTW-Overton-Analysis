"""Stage 6: apply filter_rules -> include / exclusion_reason / review_flags (no network)."""
from __future__ import annotations

import pandas as pd

from . import filter_rules as fr
from .normalise import load_works
from .settings import Paths


def doi_volume_floor(works: pd.DataFrame) -> pd.Series:
    """Per work: the lowest numeric volume among DOI-bearing works of its journal-year."""
    vol = pd.to_numeric(works["volume"], errors="coerce")
    has_doi = works["doi"].fillna("").astype(str).str.strip().ne("")
    key = [works["journal_key"], works["publication_year"]]
    return vol.where(has_doi).groupby(key).transform("min")


def apply_filter(works: pd.DataFrame) -> pd.DataFrame:
    df = works.copy()
    floors = doi_volume_floor(df)
    reasons, flags = [], []
    for rec, floor in zip(df.to_dict("records"), floors):
        rec["doi_volume_floor"] = floor
        reason = fr.exclusion_reason(rec)
        reasons.append(reason)
        flags.append(";".join(fr.review_flags(rec, excluded=bool(reason))))
    df["include"] = [not r for r in reasons]
    df["exclusion_reason"] = reasons
    df["review_flags"] = flags
    df["filter_version"] = fr.FILTER_VERSION
    df["rules_fingerprint"] = fr.rules_fingerprint()
    return df


def rule_of(reason: str) -> str:
    """`E_TYPE:erratum` -> `E_TYPE`."""
    return reason.split(":", 1)[0] if reason else ""


def run(paths: Paths) -> pd.DataFrame:
    df = apply_filter(load_works(paths))
    df.to_csv(paths.works_filtered, index=False, encoding="utf-8")
    return df


def summary(df: pd.DataFrame) -> str:
    lines = [f"filter {fr.FILTER_VERSION} ({fr.rules_fingerprint()}): "
             f"{int(df['include'].sum())} included, {int((~df['include']).sum())} excluded "
             f"of {len(df)}"]
    by_reason = df.loc[~df["include"], "exclusion_reason"].value_counts()
    for reason, n in by_reason.items():
        lines.append(f"  {reason:<28} {n}")
    flags = df.loc[df["include"], "review_flags"].str.split(";").explode()
    flags = flags[flags.ne("") & flags.notna()].value_counts()
    for code, n in flags.items():
        lines.append(f"  flag {code:<23} {n} (included works)")
    by_j = df.groupby("journal_key")["include"].agg(included="sum", total="size")
    by_j["excluded"] = by_j["total"] - by_j["included"]
    lines.append("  by journal (included / excluded):")
    for jk, r in by_j.iterrows():
        lines.append(f"    {jk:<12} {int(r['included']):>6} / {int(r['excluded'])}")
    return "\n".join(lines)
