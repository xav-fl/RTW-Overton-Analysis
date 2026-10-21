"""Stage 2 outputs (no network): coded dataset, validation sample, agreement, report.

`assemble` joins the latest valid answer per paper under one run key onto the
Stage 1 papers, adds the features computed in code, and writes
data/release/papers_coded.csv and author_disciplines.csv. Fields read from the
abstract are left blank for papers coded from their title alone.
"""
from __future__ import annotations

import json

import pandas as pd

from . import features, llm_code, settings
from .settings import Paths

#: LLM fields that depend on the abstract; blank when only the title was sent.
ABSTRACT_FIELDS = (["llm_research_type", "llm_empirical_design", "llm_primary_policy_category",
                    "llm_policy_reference", "llm_jargon", "llm_sentence_complexity",
                    "llm_is_review", "llm_is_empirical", "llm_causal_design"]
                   + [f"llm_cat_{c}" for c in llm_code.POLICY_CATEGORIES])

#: Fields a human coder fills in the validation sample, and the coded column each is compared with.
HUMAN_FIELDS = {
    "human_item_type": "llm_item_type",
    "human_research_type": "llm_research_type",
    "human_empirical_design": "llm_empirical_design",
    **{f"human_cat_{c}": f"llm_cat_{c}" for c in llm_code.POLICY_CATEGORIES},
    "human_primary_policy_category": "llm_primary_policy_category",
    "human_policy_reference": "llm_policy_reference",
    "human_jargon": "llm_jargon",
    "human_sentence_complexity": "llm_sentence_complexity",
    "human_jel_primary_major": "llm_jel_primary_major",
    "human_multidisciplinary": "multidisciplinary",
}
SCALE_FIELDS = {"human_jargon", "human_sentence_complexity"}


def current_run_key(paths: Paths, model: str = settings.LLM_MODEL,
                    effort: str = settings.LLM_EFFORT) -> str:
    return llm_code.run_key(llm_code.system_prompt(paths), model, effort)


def latest_answers(paths: Paths, key: str) -> dict[str, dict]:
    """custom_id -> the latest ok record under this run key."""
    out: dict[str, dict] = {}
    for r in llm_code.Store(paths).records():
        if r["run_key"] == key and r["status"] == "ok":
            out[r["custom_id"]] = r
    return out


def _coded_row(rec: dict, n_sent: int, jel_valid: set[str]) -> tuple[dict, list[str]]:
    ans, problems = llm_code.validate(rec["answer"], n_sent, jel_valid)
    cats = ans.get("policy_categories") or {}
    codes = ans["jel_codes"]
    row = {
        "llm_item_type": ans.get("item_type"),
        "llm_topic_label": ans.get("topic_label"),
        "llm_jel_codes": "; ".join(codes),
        "llm_jel_primary": codes[0] if codes else None,
        "llm_jel_primary_major": codes[0][0] if codes else None,
        "llm_research_type": ans.get("research_type"),
        "llm_empirical_design": ans.get("empirical_design"),
        **{f"llm_cat_{c}": bool(cats.get(c)) for c in llm_code.POLICY_CATEGORIES},
        "llm_n_policy_categories": sum(bool(cats.get(c)) for c in llm_code.POLICY_CATEGORIES),
        "llm_primary_policy_category": ans.get("primary_policy_category"),
        "llm_policy_reference": ans.get("policy_reference"),
        "llm_jargon": ans.get("jargon"),
        "llm_sentence_complexity": ans.get("sentence_complexity"),
        "llm_is_review": (ans.get("item_type") == "review_article"
                          or ans.get("research_type") == "review_or_synthesis"),
        "llm_is_empirical": ans.get("research_type") in ("empirical", "theory_and_empirical"),
        "llm_causal_design": ans.get("empirical_design") in ("experimental",
                                                             "quasi_experimental"),
        "llm_notes": ans.get("notes"),
        "llm_problems": " | ".join(problems),
        "llm_answered_model": rec.get("answered_model"),
        "llm_route": rec.get("route"),
    }
    row.update(features.discipline_summary(ans["author_disciplines"]))
    return row, ans["author_disciplines"]


def coded_columns() -> list[str]:
    """Every column `_coded_row` produces, so the output has them even before any coding."""
    answer = {"jel_codes": [], "policy_categories": {}, "author_disciplines": []}
    row, _ = _coded_row({"answer": answer}, 0, set())
    return list(row)


def assemble(paths: Paths, key: str) -> pd.DataFrame:
    df = llm_code.load_inputs(paths)
    answers = latest_answers(paths, key)
    jel_valid = llm_code.jel_valid_codes(paths)
    auths = features.author_affiliations(
        pd.read_csv(paths.authorships_stage1, low_memory=False))
    coded, disc_rows = [], []
    for r in df.to_dict("records"):
        rec = answers.get(r["custom_id"])
        row = {"openalex_id": r["openalex_id"]}
        if rec is None:
            row["llm_coded_from"] = "not_coded"
        else:
            vals, discs = _coded_row(rec, int(r["n_authors_sent"]), jel_valid)
            row.update(vals)
            row["llm_coded_from"] = "abstract" if r["has_usable_abstract"] else "title_only"
            if not r["has_usable_abstract"]:
                for f in ABSTRACT_FIELDS:
                    row[f] = None
            for a, d in zip(auths.get(r["openalex_id"], []), discs):
                disc_rows.append({"openalex_id": r["openalex_id"],
                                  "author_order": a["author_order"],
                                  "author_id": a["author_id"], "discipline": d,
                                  "affiliation": a["affiliation"],
                                  "institutions": a["institutions"]})
        coded.append(row)
    coded = pd.DataFrame(coded).reindex(columns=["openalex_id", "llm_coded_from"]
                                        + coded_columns())
    out = df.drop(columns=["user_message", "custom_id"]).merge(
        coded, on="openalex_id", how="left", validate="one_to_one")
    out["llm_run_key"] = key
    out["llm_codebook_version"] = settings.LLM_CODEBOOK_VERSION
    out = out.join(_jel_agreement(out))
    paths.release.mkdir(parents=True, exist_ok=True)
    out.to_csv(paths.papers_coded, index=False, encoding="utf-8")
    pd.DataFrame(disc_rows).to_csv(paths.author_disciplines, index=False, encoding="utf-8")
    return out


def _jel_agreement(df: pd.DataFrame) -> pd.DataFrame:
    """Compare the model's JEL codes with the authors' own, where the abstract lists them."""
    any_overlap, major_match = [], []
    for author, llm in zip(df["jel_codes_author"].fillna(""), df.get("llm_jel_codes",
                                                                    pd.Series(dtype=str)).fillna("")):
        a = {c for c in author.split("; ") if c}
        m = [c for c in llm.split("; ") if c]
        if not a or not m:
            any_overlap.append(None)
            major_match.append(None)
            continue
        a3 = {c[:3] for c in a}
        any_overlap.append(bool(a3 & set(m)))
        major_match.append(m[0][0] in {c[0] for c in a})
    return pd.DataFrame({"llm_jel_overlaps_author": any_overlap,
                         "llm_jel_primary_major_in_author": major_match}, index=df.index)


# -- validation sample --------------------------------------------------------

def validation_sample(paths: Paths, n: int = settings.LLM_VALIDATION_SIZE,
                      seed: int = settings.LLM_VALIDATION_SEED) -> pd.DataFrame:
    """A journal-stratified sample of papers with abstracts, with blank columns for human coders.

    Drawn from Stage 1 data only, so it does not depend on what the model answered.
    """
    df = llm_code.load_inputs(paths)
    pool = df[df["has_usable_abstract"]]
    share = pool["journal_key"].value_counts(normalize=True)
    take = (share * n).round().astype(int).clip(lower=1)
    while take.sum() > n:
        take[take.idxmax()] -= 1
    while take.sum() < n:
        take[take.idxmax()] += 1
    parts = [pool[pool["journal_key"] == j].sample(k, random_state=seed)
             for j, k in take.items()]
    s = pd.concat(parts).sort_values(["journal_key", "publication_year"])
    out = s[["openalex_id", "custom_id", "doi", "journal_key", "publication_year", "title",
             "abstract_clean", "user_message"]].rename(columns={"user_message": "record_sent"})
    for col in HUMAN_FIELDS:
        out[col] = ""
    out["human_coder"] = ""
    out["human_notes"] = ""
    paths.review.mkdir(parents=True, exist_ok=True)
    out.to_csv(paths.validation_sample, index=False, encoding="utf-8")
    return out


# -- agreement ----------------------------------------------------------------

def _norm(v):
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    s = str(v).strip().lower()
    if s in ("true", "yes", "y", "1", "1.0"):
        return "1"
    if s in ("false", "no", "n", "0", "0.0"):
        return "0"
    try:
        return str(int(float(s)))
    except ValueError:
        return s


def cohen_kappa(a: list[str], b: list[str]) -> float | None:
    n = len(a)
    if not n:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    labels = set(a) | set(b)
    pe = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    return None if pe == 1 else round((po - pe) / (1 - pe), 3)


def agreement(paths: Paths, human_file, coded: pd.DataFrame | None = None) -> pd.DataFrame:
    """Per-field agreement between a filled-in validation sample and the coded dataset."""
    human = pd.read_csv(human_file, dtype=str, keep_default_na=False)
    if coded is None:
        coded = pd.read_csv(paths.papers_coded, low_memory=False)
    m = human.merge(coded, on="openalex_id", how="inner", suffixes=("", "_coded"))
    rows = []
    for hcol, ccol in HUMAN_FIELDS.items():
        pairs = [(_norm(h), _norm(c)) for h, c in zip(m[hcol], m[ccol])]
        pairs = [(h, c) for h, c in pairs if h is not None and c is not None]
        a, b = [p[0] for p in pairs], [p[1] for p in pairs]
        row = {"field": hcol.removeprefix("human_"), "n": len(pairs),
               "agreement": round(sum(x == y for x, y in pairs) / len(pairs), 3) if pairs else None,
               "cohen_kappa": cohen_kappa(a, b)}
        if hcol in SCALE_FIELDS and pairs:
            row["within_one"] = round(sum(abs(int(x) - int(y)) <= 1 for x, y in pairs)
                                      / len(pairs), 3)
        rows.append(row)
    out = pd.DataFrame(rows)
    paths.reports.mkdir(parents=True, exist_ok=True)
    out.to_csv(paths.llm_agreement, index=False, encoding="utf-8")
    return out


# -- report -------------------------------------------------------------------

def _dist(s: pd.Series) -> str:
    vc = s.value_counts(dropna=True)
    tot = vc.sum()
    return "\n".join(f"| {k} | {v} | {v / tot:.1%} |" for k, v in vc.items())


def report(paths: Paths, coded: pd.DataFrame, key: str) -> None:
    recs = [r for r in llm_code.Store(paths).records() if r["run_key"] == key]
    status = pd.Series([r["status"] for r in recs]).value_counts().to_dict()
    use = llm_code.usage_summary(recs)
    c = coded[coded["llm_coded_from"] == "abstract"]
    jel = coded[coded["llm_jel_overlaps_author"].notna()]
    lines = [
        f"# Stage 2 LLM coding report — codebook {settings.LLM_CODEBOOK_VERSION}, run {key}",
        "",
        f"Papers: {len(coded)}; coded from abstract: {len(c)}; "
        f"from title only: {(coded['llm_coded_from'] == 'title_only').sum()}; "
        f"not coded: {(coded['llm_coded_from'] == 'not_coded').sum()}.",
        f"Responses under this run key by status: {json.dumps(status)}.",
        f"Answers with a validation problem: {(coded['llm_problems'].fillna('') != '').sum()} "
        f"(see column llm_problems).",
        f"Answered by a fallback model: "
        f"{(coded['llm_answered_model'].notna() & (coded['llm_answered_model'] != settings.LLM_MODEL)).sum()}.",
        "",
        f"API usage: {use['calls']} calls, {use['input_tokens']} input, "
        f"{use['cache_read_input_tokens']} cache-read, {use['cache_creation_input_tokens']} "
        f"cache-write, {use['output_tokens']} output tokens; ${use['usd']} "
        f"(${use['usd_per_call']} per call).",
        "",
        "## JEL codes against the authors' own",
        "",
        f"{len(jel)} coded papers list JEL codes in the abstract (removed before coding). "
        f"Model and authors share at least one code: "
        f"{jel['llm_jel_overlaps_author'].astype(bool).mean():.1%}; the model's primary "
        f"code's major field is among the authors': "
        f"{jel['llm_jel_primary_major_in_author'].astype(bool).mean():.1%}." if len(jel) else
        "No coded paper lists JEL codes in its abstract.",
        "",
    ]
    for title, col in [("Item type (all coded)", "llm_item_type"),
                       ("Research type", "llm_research_type"),
                       ("Empirical design", "llm_empirical_design"),
                       ("Primary policy category", "llm_primary_policy_category"),
                       ("Policy reference", "llm_policy_reference"),
                       ("JEL primary major field", "llm_jel_primary_major"),
                       ("Jargon (1-5)", "llm_jargon"),
                       ("Sentence complexity (1-5)", "llm_sentence_complexity"),
                       ("Multidisciplinary team", "multidisciplinary"),
                       ("Multidisciplinary beyond economics/business",
                        "multidisciplinary_beyond_econ_business")]:
        src = coded[coded["llm_coded_from"] != "not_coded"] if col in (
            "llm_item_type", "llm_jel_primary_major", "multidisciplinary",
            "multidisciplinary_beyond_econ_business") else c
        lines += [f"## {title}", "", "| value | n | share |", "|---|---|---|",
                  _dist(src[col]), ""]
    cats = pd.Series({k: c[f"llm_cat_{k}"].astype(bool).mean()
                      for k in llm_code.POLICY_CATEGORIES})
    lines += ["## Policy categories (share yes, abstract-coded papers)", "",
              "| category | share |", "|---|---|"]
    lines += [f"| {k} | {v:.1%} |" for k, v in cats.items()]
    paths.reports.mkdir(parents=True, exist_ok=True)
    paths.llm_report.write_text("\n".join(lines) + "\n", encoding="utf-8")
