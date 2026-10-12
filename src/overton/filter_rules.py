"""Rule definitions for separating research papers from other items.

Bump FILTER_VERSION whenever a rule changes meaning. `rules_fingerprint()`
hashes the definitions below, so any edit to them moves the fingerprint even
if the version is not bumped; both are written into the outputs.

Matching conventions (brief, Stage 6): case-insensitive; title stripped of
surrounding whitespace and trailing punctuation; curly quotes and dashes
normalised. `eq` = whole title equals the phrase; `start` = title starts with
the phrase followed by a word boundary; `end` = title ends with the phrase.
A ":" in a phrase also matches "—", "–" or " - ".

Principle: prefer missing an exclusion to wrongly excluding a research paper.
Anything uncertain is a review flag, not an exclusion.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata

FILTER_VERSION = "F2"

#: F2 (2026-10-12) adds E_MISDATED and E_NONENGLISH_NO_DOI, applied after the F1
#: rules. Both target OpenAlex metadata errors found in the F1 run: legacy
#: records of old papers carrying a placeholder 2016 date (AER, JEL, ...) and
#: works attached to the wrong source (Japanese steel papers under JFE). Both
#: require a missing DOI, so no DOI-bearing work can be excluded by them.

INCLUDED_TYPES = ("article", "review")

#: Exclusion rules, applied in this order; the first match sets exclusion_reason.
#: E_TYPE, E_PARATEXT and the last two test record fields; the rest test the title.
EXCLUSION_RULES: list[dict] = [
    {"code": "E_TYPE", "field": "openalex_type", "not_in": list(INCLUDED_TYPES)},
    {"code": "E_PARATEXT", "field": "is_paratext", "is_true": True},
    {"code": "E_CORRECTION",
     "words": ["erratum", "errata", "corrigendum", "corrigenda"],
     "start": ["correction to", "correction:", "corrections to", "retraction notice",
               "retraction of", "retraction:", "expression of concern"],
     "eq": ["correction", "corrections", "retraction"]},
    {"code": "E_COMMENT",
     "start": ["comment on", "comments on", "a comment on", "comment:", "reply to",
               "a reply to", "reply:", "rejoinder"],
     "eq": ["comment", "comments", "reply", "rejoinder"],
     "end": [": comment", ": comments", ": reply", ": rejoinder", ": a comment",
             ": a reply", ": comment and reply"]},
    {"code": "E_FRONTMATTER",
     "eq": ["front matter", "back matter", "issue information", "table of contents",
            "contents", "index", "volume information", "masthead", "editorial board",
            "cover", "front cover", "back cover"],
     "start": ["front matter", "back matter", "issue information", "table of contents",
               "index to volume", "author index", "subject index", "volume information"]},
    {"code": "E_ADMIN",
     "start": ["report of the editor", "report of the secretary", "report of the treasurer",
               "report of the president", "report of the committee", "minutes of the",
               "annual report of the", "news notes", "submission of manuscripts",
               "forthcoming papers", "forthcoming articles", "acknowledgment to",
               "acknowledgement to", "acknowledgments to", "list of referees",
               "referees for volume", "call for papers", "election of fellows",
               "election of officers", "fellows of the econometric society",
               "in memoriam", "obituary", "editor's note", "editors' note",
               "editorial note", "editorial:"],
     "eq": ["announcement", "announcements", "editorial", "acknowledgments",
            "acknowledgements", "referees"]},
    {"code": "E_BOOKS",
     "start": ["book review", "book reviews", "annotated listing of new books",
               "new books", "recent dissertations"],
     "eq": ["dissertations"]},
    {"code": "E_READING",
     "start": ["recommendations for further reading"],
     "eq": ["correspondence"]},
    {"code": "E_MISDATED", "field": "volume",
     "test": "no DOI, and numeric volume more than VOLUME_SLACK below the lowest "
             "volume among DOI-bearing works of the same journal-year",
     "slack": 1},
    {"code": "E_NONENGLISH_NO_DOI", "field": "language",
     "test": "no DOI, and language is set and not English", "allowed": ["en"]},
]

VOLUME_SLACK = 1

#: Review flags. Title patterns are regexes over the normalised title.
FLAG_RULES: list[dict] = [
    {"code": "F_SHORT", "test": "page_count <= 3"},
    {"code": "F_NO_AUTHORS", "test": "n_authors == 0"},
    {"code": "F_NO_ABSTRACT_NO_DOI", "test": "no abstract and no doi"},
    {"code": "F_RETRACTED", "test": "is_retracted"},
    {"code": "F_COMMENT_WORD", "test": "title regex, only if not excluded",
     "regex": r"\b(?:comment\w*|repl(?:y|ies)|rejoinder\w*)\b|^response to\b"},
    {"code": "F_ADMIN_WORD", "test": "title regex, only if not excluded",
     "regex": r"^(?:reports?|announcements?|index(?:es)?|editorials?|corrections?)\b"},
    {"code": "F_JEL_NO_ABSTRACT", "test": "journal_key == jel and no abstract"},
    {"code": "F_INTRO", "test": "title regex",
     "regex": r"^(?:introduction to\b|symposium|introduction\s*(?::|—|–|\s-\s)|foreword)"},
]


def rules_fingerprint() -> str:
    """sha256 (first 12 hex chars) of the rule definitions and version."""
    blob = json.dumps({"version": FILTER_VERSION, "exclusions": EXCLUSION_RULES,
                       "volume_slack": VOLUME_SLACK,
                       "flags": FLAG_RULES}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


# -- title matching ---------------------------------------------------------

_QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'",
                         "′": "'", "“": '"', "”": '"', "„": '"',
                         "‐": "-", "‑": "-", "‒": "-", "−": "-",
                         "―": "—", " ": " "})
_TRAILING = re.compile(r"[\s.,;:!?·*]+$")
_COLON = r"(?:\s*:|\s*[—–]|\s+-)"     # ":" also accepts em dash, en dash, " - "


def normalise_title(title) -> str:
    if title is None or (isinstance(title, float) and title != title):
        return ""
    t = unicodedata.normalize("NFKC", str(title)).translate(_QUOTES)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return _TRAILING.sub("", t)


def _phrase_regex(phrase: str) -> str:
    parts = []
    for ch in phrase:
        if ch == ":":
            parts.append(_COLON)
        elif ch == " ":
            parts.append(r"\s+")
        else:
            parts.append(re.escape(ch))
    rx = "".join(parts)
    # A phrase ending in ":" must not then need a following space to be optional.
    return rx.replace(_COLON + r"\s+", _COLON + r"\s*")


def _compile(rule: dict) -> re.Pattern | None:
    alts = []
    for p in rule.get("eq", []):
        alts.append("^" + _phrase_regex(p) + "$")
    for p in rule.get("start", []):
        tail = r"(?!\w)" if p[-1].isalnum() else ""
        alts.append("^" + _phrase_regex(p) + tail)
    for p in rule.get("end", []):
        head = r"(?<!\w)" if p[0].isalnum() else ""
        alts.append(head + _phrase_regex(p) + "$")
    if rule.get("words"):
        alts.append(r"\b(?:" + "|".join(map(re.escape, rule["words"])) + r")\b")
    return re.compile("|".join(alts)) if alts else None


_TITLE_RULES = [(r["code"], _compile(r)) for r in EXCLUSION_RULES if "field" not in r]


def _num(v):
    try:
        f = float(str(v).strip())
    except (TypeError, ValueError):
        return None
    return None if f != f else f
_FLAG_REGEX = {r["code"]: re.compile(r["regex"]) for r in FLAG_RULES if "regex" in r}


def _truthy(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes")
    try:
        return bool(v) and v == v      # NaN -> False
    except (TypeError, ValueError):
        return False


def exclusion_reason(rec: dict) -> str:
    """First matching exclusion rule code ('' if none)."""
    t = rec.get("openalex_type")
    t = "" if t is None or (isinstance(t, float) and t != t) else str(t)
    if t not in INCLUDED_TYPES:
        return f"E_TYPE:{t or 'none'}"
    if _truthy(rec.get("is_paratext")):
        return "E_PARATEXT"
    title = normalise_title(rec.get("title"))
    for code, rx in _TITLE_RULES:
        if title and rx.search(title):
            return code
    if _blank(rec.get("doi")):
        vol, floor = _num(rec.get("volume")), _num(rec.get("doi_volume_floor"))
        if vol is not None and floor is not None and vol < floor - VOLUME_SLACK:
            return "E_MISDATED"
        lang = "" if _blank(rec.get("language")) else str(rec["language"]).strip().lower()
        if lang and lang != "en":
            return "E_NONENGLISH_NO_DOI"
    return ""


def _blank(v) -> bool:
    return v is None or (isinstance(v, float) and v != v) or str(v).strip() == ""


def review_flags(rec: dict, excluded: bool) -> list[str]:
    title = normalise_title(rec.get("title"))
    no_abstract = not _truthy(rec.get("has_abstract"))
    flags = []
    pc = rec.get("page_count")
    if not _blank(pc) and int(pc) <= 3:
        flags.append("F_SHORT")
    if int(rec.get("n_authors") or 0) == 0:
        flags.append("F_NO_AUTHORS")
    if no_abstract and _blank(rec.get("doi")):
        flags.append("F_NO_ABSTRACT_NO_DOI")
    if _truthy(rec.get("is_retracted")):
        flags.append("F_RETRACTED")
    if not excluded and _FLAG_REGEX["F_COMMENT_WORD"].search(title):
        flags.append("F_COMMENT_WORD")
    if not excluded and _FLAG_REGEX["F_ADMIN_WORD"].search(title):
        flags.append("F_ADMIN_WORD")
    if rec.get("journal_key") == "jel" and no_abstract:
        flags.append("F_JEL_NO_ABSTRACT")
    if _FLAG_REGEX["F_INTRO"].search(title):
        flags.append("F_INTRO")
    return flags


EXCLUSION_CODES = [r["code"] for r in EXCLUSION_RULES]
FLAG_CODES = [r["code"] for r in FLAG_RULES]
