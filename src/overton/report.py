"""Stage 7: release files, review samples, harvest report and run report (no network)."""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone

import pandas as pd

from . import filter_rules as fr
from . import harvest, settings
from .filter import rule_of
from .normalise import AUTHORSHIP_COLUMNS, WORK_COLUMNS, load_works
from .settings import Paths

#: Deviations from the brief, reported verbatim in section 8 of the run report.
DEVIATIONS = [
    "The repository was created empty on GitHub (RTW-Overton-Analysis) and cloned to "
    "`GITHUB CODE/Overton-Analysis`; at the user's request Claude made the initial commit "
    "(the brief and `config/journals.csv`) so that the Stage 0 preflight could pass.",
    "Dropped connections (`ConnectionError`, e.g. WinError 10054 connection resets, seen "
    "repeatedly on this network) are retried with the same backoff as timeouts. The brief "
    "lists timeouts only; a reset connection is the same transient failure.",
    "The rate limiter spaces requests at least 0.2 s apart (5/s), counting retries.",
    "The empty terminal page of each cursor walk (results empty, next_cursor null) is "
    "requested but not saved; `n_pages` counts saved pages with results.",
    "The manifest is append-only (one row per attempt); the latest row per journal-year "
    "is that journal-year's state.",
    "A resolved source whose `type` is not `journal` gets status `not_journal` (the brief "
    "names no status for this case; any non-`ok` status fails the gate).",
    "OpenAlex's `/rate-limit` echoes a masked form of the key; the client drops that field "
    "and stores only the `rate_limit` block.",
]

DEVIATIONS.append(
    "Filter F2 (added after reviewing the F1 run, at the user's request) adds two exclusion "
    "rules applied after the F1 rules, both limited to works without a DOI: `E_MISDATED` "
    "(numeric volume more than 1 below the lowest volume among DOI-bearing works of the same "
    "journal-year; catches legacy records of 1969-1998 AER/JEL papers that OpenAlex dates "
    "2016-01-01) and `E_NONENGLISH_NO_DOI` (language set and not English; catches Japanese "
    "steel-engineering papers attached to the Journal of Financial Economics source). "
    "Neither rule is in the brief.")

PAPER_EXTRA = ["in_top15_economics_only", "in_top15_all_fields", "filter_version",
               "rules_fingerprint"]


def _git_commit(paths: Paths) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=paths.root,
                             capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain", "--", "src", "config", "tests"], cwd=paths.root,
                               capture_output=True, text=True).stdout.strip()
        return out.stdout.strip() + (" (+uncommitted changes)" if dirty else "")
    except Exception:                                # noqa: BLE001
        return "unknown"


def _pct(n, d) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def _sample_excluded(exc: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Round-robin across exclusion_reason so every reason is represented."""
    if len(exc) <= n:
        return exc
    groups = [g.sample(frac=1, random_state=seed)
              for _, g in sorted(exc.groupby("exclusion_reason"), key=lambda t: t[0])]
    picked, i = [], 0
    while len(picked) < n:
        progressed = False
        for g in groups:
            if i < len(g) and len(picked) < n:
                picked.append(g.iloc[i])
                progressed = True
        if not progressed:
            break
        i += 1
    return pd.DataFrame(picked)


def write_release(paths: Paths, df: pd.DataFrame, auth: pd.DataFrame) -> dict:
    paths.release.mkdir(parents=True, exist_ok=True)
    journals = pd.read_csv(paths.journals, dtype=str, keep_default_na=False)
    top = journals[["journal_key", "in_top15_economics_only", "in_top15_all_fields"]]
    inc = df[df["include"]].merge(top, on="journal_key", how="left")
    inc[WORK_COLUMNS + PAPER_EXTRA].to_csv(paths.release / "papers_stage1.csv",
                                           index=False, encoding="utf-8-sig")
    auth[auth["openalex_id"].isin(set(inc["openalex_id"]))][AUTHORSHIP_COLUMNS].to_csv(
        paths.release / "authorships_stage1.csv", index=False, encoding="utf-8-sig")
    df[~df["include"]][WORK_COLUMNS + ["exclusion_reason", "review_flags", "filter_version",
                                       "rules_fingerprint"]].to_csv(
        paths.release / "excluded_items.csv", index=False, encoding="utf-8-sig")

    for old in paths.release.glob("overton_doi_batch_*.txt"):
        old.unlink()
    dois = sorted({d.strip().lower() for d in inc["doi"] if d and d.strip()})
    size = settings.DOI_BATCH_SIZE
    batches = [dois[i:i + size] for i in range(0, len(dois), size)]
    for k, batch in enumerate(batches, start=1):
        (paths.release / f"overton_doi_batch_{k:02d}.txt").write_text(
            "\n".join(batch) + "\n", encoding="utf-8")
    return {"n_dois": len(dois), "n_batches": len(batches)}


def write_review(paths: Paths, df: pd.DataFrame) -> None:
    paths.review.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(paths.journals_resolved, paths.review / "journals_resolved_review.csv")
    seed, n = settings.SAMPLE_SEED, settings.SAMPLE_SIZE
    inc = df[df["include"]]
    cols = ["journal_key", "publication_year", "title", "openalex_type", "page_count", "doi",
            "review_flags"]
    s = inc.sample(n=min(n, len(inc)), random_state=seed)[cols].rename(
        columns={"publication_year": "year"})
    s.to_csv(paths.review / "sample_included.csv", index=False, encoding="utf-8-sig")
    exc = df[~df["include"]]
    _sample_excluded(exc, n, seed)[["exclusion_reason"] + cols].rename(
        columns={"publication_year": "year"}).to_csv(
        paths.review / "sample_excluded.csv", index=False, encoding="utf-8-sig")
    inc[inc["review_flags"].ne("")][["openalex_id"] + cols].rename(
        columns={"publication_year": "year"}).to_csv(
        paths.review / "flagged.csv", index=False, encoding="utf-8-sig")


def harvest_report(paths: Paths, df: pd.DataFrame, auth: pd.DataFrame) -> pd.DataFrame:
    state = harvest.latest_manifest(paths)
    with_inst = set(auth.loc[auth["institution_id"].notna() & auth["institution_id"].ne(""),
                             "openalex_id"])
    df = df.assign(rule=df["exclusion_reason"].map(rule_of),
                   any_inst=df["openalex_id"].isin(with_inst))
    rows = []
    for (jk, year), m in sorted(state.items()):
        g = df[(df["journal_key"] == jk) & (df["publication_year"] == year)]
        inc = g[g["include"]]
        row = {"journal_key": jk, "year": year,
               "expected_count": int(m["expected_count"] or 0),
               "retrieved_count": int(m["retrieved_count"] or 0),
               "locations_count": m["locations_count"],
               "included": len(inc), "excluded": int((~g["include"]).sum())}
        for code in fr.EXCLUSION_CODES:
            row[code] = int((g["rule"] == code).sum())
        row.update({
            "flagged": int(inc["review_flags"].ne("").sum()),
            "pct_with_doi": _pct(inc["doi"].ne("").sum(), len(inc)),
            "pct_with_abstract": _pct(inc["has_abstract"].astype(bool).sum(), len(inc)),
            "pct_with_any_institution": _pct(inc["any_inst"].sum(), len(inc)),
            "n_abstract_mentions_jel": int(inc["abstract_mentions_jel"].astype(bool).sum()),
        })
        rows.append(row)
    hr = pd.DataFrame(rows)
    hr.to_csv(paths.harvest_report, index=False, encoding="utf-8")
    return hr


def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in df.itertuples(index=False):
        lines.append("| " + " | ".join(str(v) for v in r) + " |")
    return "\n".join(lines)


def _api_usage(paths: Paths) -> list[dict]:
    if not paths.api_usage.exists():
        return []
    return [json.loads(l) for l in paths.api_usage.read_text(encoding="utf-8").splitlines() if l]


def run_report(paths: Paths, df: pd.DataFrame, hr: pd.DataFrame, rel: dict) -> str:
    inc, exc = df[df["include"]], df[~df["include"]]
    usage = _api_usage(paths)
    req = sum(u.get("requests") or 0 for u in usage)
    usd = sum((u.get("usd_used_after") or 0) - (u.get("usd_used_before") or 0) for u in usage)
    last = usage[-1] if usage else {}

    L = ["# Stage 1 run report", ""]
    L += ["## 1. Run", "",
          f"- Report generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC",
          f"- Harvest dates: {', '.join(sorted(set(df['harvest_date'].astype(str))))}",
          f"- Git commit: `{_git_commit(paths)}`",
          f"- Filter: `{fr.FILTER_VERSION}`, rules fingerprint `{fr.rules_fingerprint()}`",
          f"- OpenAlex usage logged across networked commands: {req} successful requests, "
          f"${usd:.4f} of the daily allowance (remaining after last command: "
          f"${last.get('usd_remaining_after', 'n/a')}; resets {last.get('resets_at', 'n/a')})",
          ""]
    for u in usage:
        L.append(f"  - {u['at']} `{u['command']}`: {u['requests']} requests "
                 f"({u['attempts']} attempts incl. retries)")
    L.append("")

    L += ["## 2. Totals", "",
          f"- Works harvested: {len(df)}",
          f"- Included: {len(inc)}",
          f"- Excluded: {len(exc)}",
          f"- Included works with at least one review flag: {int(inc['review_flags'].ne('').sum())}",
          f"- DOIs in Overton batches: {rel['n_dois']} in {rel['n_batches']} file(s)", "",
          "Excluded by reason:", ""]
    L.append(_md_table(exc["exclusion_reason"].value_counts().rename_axis("reason")
                       .reset_index(name="n")))
    L += ["", "Review flags on included works:", ""]
    fl = inc["review_flags"].str.split(";").explode()
    fl = fl[fl.ne("") & fl.notna()].value_counts().rename_axis("flag").reset_index(name="n")
    L.append(_md_table(fl) if len(fl) else "(none)")
    L.append("")

    L += ["## 3. By journal (all years pooled)", ""]
    g = df.groupby("journal_key")
    bj = pd.DataFrame({
        "harvested": g.size(),
        "included": g["include"].sum(),
    })
    gi = inc.groupby("journal_key")
    bj["pct_with_abstract"] = (100 * gi["has_abstract"].mean()).round(1)
    bj["pct_with_doi"] = (100 * gi["doi"].apply(lambda s: s.ne("").mean())).round(1)
    journals = pd.read_csv(paths.journals, dtype=str, keep_default_na=False)["journal_key"]
    bj = bj.reindex(journals).fillna(0).reset_index()
    bj[["harvested", "included"]] = bj[["harvested", "included"]].astype(int)
    L += [_md_table(bj), ""]

    L += ["## 4. Journal-years where locations_count differs from expected_count", ""]
    hr2 = hr.assign(locations_count=pd.to_numeric(hr["locations_count"], errors="coerce"))
    diff = hr2[hr2["locations_count"] != hr2["expected_count"]][
        ["journal_key", "year", "expected_count", "locations_count"]]
    L += [_md_table(diff.astype({"locations_count": "Int64"})) if len(diff) else "(none)", ""]

    L += ["## 5. Journal-years with zero works", ""]
    zero = hr[hr["expected_count"] == 0][["journal_key", "year"]]
    L += [_md_table(zero) if len(zero) else "(none)", ""]

    L += ["## 6. Duplicate DOIs (two or more works sharing one DOI)", ""]
    d = df[df["doi"].ne("")]
    dup = d[d["doi"].duplicated(keep=False)].sort_values("doi")
    if len(dup):
        L.append(f"{dup['doi'].nunique()} DOIs shared by {len(dup)} works:")
        L.append("")
        L.append(_md_table(dup[["doi", "openalex_id", "journal_key", "publication_year",
                                "openalex_type", "include", "title"]]))
    else:
        L.append("(none)")
    L.append("")

    L += ["## 7. Included abstracts containing \"JEL\"", "",
          f"{int(inc['abstract_mentions_jel'].astype(bool).sum())} of {len(inc)} included works "
          f"(of which {int(inc['has_abstract'].astype(bool).sum())} have an abstract).", ""]
    hundred = df[df["n_authors"] == 100]
    L += ["Works with exactly 100 authorships (OpenAlex truncation limit): "
          f"{len(hundred)}" + (": " + ", ".join(hundred["openalex_id"]) if len(hundred) else ""),
          ""]

    L += ["## 8. Deviations from the brief", ""]
    L += [f"- {d}" for d in DEVIATIONS]
    L.append("")
    text = "\n".join(L)
    paths.run_report.write_text(text, encoding="utf-8")
    return text


def run(paths: Paths) -> dict:
    df = load_works(paths, filtered=True)
    df["include"] = df["include"].astype(str).str.lower().eq("true")
    for c in ("has_abstract", "abstract_mentions_jel"):
        df[c] = df[c].astype(str).str.lower().eq("true")
    auth = pd.read_csv(paths.authorships, dtype=str, keep_default_na=False, encoding="utf-8")
    rel = write_release(paths, df, auth)
    write_review(paths, df)
    hr = harvest_report(paths, df, auth)
    run_report(paths, df, hr, rel)
    return rel
