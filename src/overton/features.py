"""Stage 2 features computed in code, without a model (no network).

Author-supplied JEL codes are parsed out of the abstract and the abstract is
cleaned of them, so the model codes JEL independently and the readability
measures are not distorted by a list of codes. Readability uses the standard
Flesch formulas with a vowel-group syllable count.
"""
from __future__ import annotations

import math
import re

import pandas as pd

#: Abstracts shorter than this are treated as missing: the short ones in the
#: data are front-matter blurbs ("11 papers, 6 review essays..."), not abstracts.
MIN_ABSTRACT_WORDS = 30
#: Longer than this is more likely an introduction than an abstract; kept but flagged.
LONG_ABSTRACT_WORDS = 500
#: Authors beyond this many are not sent to the model (affects a handful of papers).
MAX_AUTHORS_SENT = 40

_JEL_CODE = re.compile(r"\b[A-Z]\d{1,2}\b")
#: "(JEL I21, I23)", "JEL Classification: D82; G21", "JEL codes: E52 E58" — the
#: label followed by a run of codes, optionally parenthesised.
_JEL_BLOCK = re.compile(
    r"\(?\s*\bJEL\b(?:\s+(?:classifications?|codes?|categories))?\s*(?:numbers?)?\s*[:.,]?\s*"
    r"((?:[A-Z]\d{1,2}\b[\s,;.]*)+)\)?",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.!?]+(?=\s+|$)")
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")
_VOWELS = re.compile(r"[aeiouy]+")


def author_jel_codes(abstract: str) -> list[str]:
    """JEL codes the authors listed in the abstract, in order, de-duplicated."""
    codes: list[str] = []
    for m in _JEL_BLOCK.finditer(abstract or ""):
        for c in _JEL_CODE.findall(m.group(1).upper()):
            if c not in codes:
                codes.append(c)
    return codes


def clean_abstract(abstract: str) -> str:
    """The abstract with any JEL code list removed."""
    text = _JEL_BLOCK.sub(" ", abstract or "")
    return re.sub(r"\s+", " ", text).strip()


def syllables(word: str) -> int:
    w = word.lower().strip("'-")
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|[^laeiouy]ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(_VOWELS.findall(w)))


def readability(text: str) -> dict:
    """Sentence, word and syllable measures, and the two Flesch scores."""
    words = _WORD.findall(text or "")
    n_words = len(words)
    if not n_words:
        return {k: None for k in READABILITY_COLUMNS}
    n_sent = max(1, len(_SENTENCE_END.findall(text)))
    sylls = [syllables(w) for w in words]
    wps = n_words / n_sent
    spw = sum(sylls) / n_words
    return {
        "abs_n_sentences": n_sent,
        "abs_words_per_sentence": round(wps, 2),
        "abs_chars_per_word": round(sum(len(w) for w in words) / n_words, 2),
        "abs_share_polysyllabic": round(sum(s >= 3 for s in sylls) / n_words, 4),
        "abs_flesch_reading_ease": round(206.835 - 1.015 * wps - 84.6 * spw, 2),
        "abs_flesch_kincaid_grade": round(0.39 * wps + 11.8 * spw - 15.59, 2),
    }


READABILITY_COLUMNS = [
    "abs_n_sentences", "abs_words_per_sentence", "abs_chars_per_word",
    "abs_share_polysyllabic", "abs_flesch_reading_ease", "abs_flesch_kincaid_grade",
]


def paper_features(papers: pd.DataFrame) -> pd.DataFrame:
    """One row per paper: cleaned abstract, author JEL codes, usability flags, readability."""
    rows = []
    for r in papers[["openalex_id", "abstract"]].itertuples(index=False):
        raw = r.abstract if isinstance(r.abstract, str) else ""
        clean = clean_abstract(raw)
        n = len(clean.split())
        usable = n >= MIN_ABSTRACT_WORDS
        codes = author_jel_codes(raw)
        row = {
            "openalex_id": r.openalex_id,
            "abstract_clean": clean,
            "abstract_clean_word_count": n,
            "has_usable_abstract": usable,
            "abstract_suspect_long": n > LONG_ABSTRACT_WORDS,
            "jel_codes_author": "; ".join(codes),
            "n_jel_codes_author": len(codes),
        }
        row.update(readability(clean) if usable else {k: None for k in READABILITY_COLUMNS})
        rows.append(row)
    return pd.DataFrame(rows)


def _join_unique(values) -> str:
    out: list[str] = []
    for v in values:
        if isinstance(v, str) and v.strip() and v.strip() not in out:
            out.append(v.strip())
    return "; ".join(out)


def author_affiliations(authorships: pd.DataFrame) -> dict[str, list[dict]]:
    """openalex_id -> authors in order, each with its affiliation text and institutions.

    authorships has one row per author x institution; this collapses it back to
    one entry per author.
    """
    out: dict[str, list[dict]] = {}
    a = authorships.sort_values(["openalex_id", "author_order"])
    for (wid, order), g in a.groupby(["openalex_id", "author_order"], sort=False):
        out.setdefault(wid, []).append({
            "author_order": int(order),
            "author_id": g["author_id"].iloc[0],
            "affiliation": _join_unique(g["raw_affiliation_strings"]),
            "institutions": _join_unique(g["institution_name"]),
        })
    return out


#: Disciplines grouped for the "beyond economics and business" measure.
ECON_BUSINESS = frozenset({"economics", "finance_accounting", "business_management"})


def discipline_summary(disciplines: list[str]) -> dict:
    """Team-level measures from the per-author disciplines the model returned."""
    known = [d for d in disciplines if d and d != "unknown"]
    distinct = sorted(set(known))
    groups = {"econ_business" if d in ECON_BUSINESS else d for d in distinct}
    n = len(disciplines)
    return {
        "author_disciplines": "; ".join(disciplines),
        "n_distinct_disciplines": len(distinct),
        "share_authors_unknown_discipline": (round((n - len(known)) / n, 3) if n else None),
        "multidisciplinary": (len(distinct) >= 2) if known else None,
        "multidisciplinary_beyond_econ_business": (len(groups) >= 2) if known else None,
        "any_author_outside_econ_business": (any(d not in ECON_BUSINESS for d in distinct)
                                             if known else None),
    }


def is_nan(v) -> bool:
    return v is None or (isinstance(v, float) and math.isnan(v))
