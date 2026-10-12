# OVERTON STAGE 1 BRIEF v1 — OpenAlex harvest of economics papers

**Issued by:** Xavier (WISE) · **Implementer:** Claude Code · **Date:** 2026-10-12
**Scoping reference:** *Overton Analysis — Scoping*, section 1 ("Scrape a dataset of economics papers")

---

## 1. Purpose

Build and run, end to end, a pipeline that downloads journal articles from the OpenAlex API for a fixed list of economics journals and years, converts them into clean tables, separates research papers from non-research items (comments, corrections, front matter, etc.), and produces:

1. a paper-level table (one row per research paper),
2. an author-level table (one row per paper × author × institution),
3. DOI lists ready to upload to Overton,
4. a run report and review samples for a human to check.

This is stage 1 of a larger project. **Do not** do anything belonging to later stages: no LLM calls, no JEL coding, no Overton access, no abstract backfilling from other sources.

You are to run all stages in sequence without waiting for approval between them. **Stop only when an automated gate in this brief fails**, and report exactly what failed. Human review happens after the run, using the review files you produce.

---

## 2. Ground rules (scope fence)

**2.1 Repository and location.**
- This pipeline has its **own repository**, separate from the EPS repository. Work only in the repository whose root is exactly `C:/Users/xavif/WISE-PC/GITHUB CODE/Overton-Analysis` (as printed by `git rev-parse --show-toplevel`). If the root differs, **stop**: a previous project lost work to edits in a stray copy.
- Create and modify files **only** inside that repository.
- You may **read** `C:/Users/xavif/WISE-PC/GITHUB CODE/RTW-Speech-Scanner-V1/scanner-code/eps-pipeline/` for reference (retry pattern, code style, Python version). You must **not** modify anything in the EPS repository or its environment.
- Do **not** create or edit `DECISIONS.md` anywhere.
- Do not push to any remote. Commit locally at the gates marked **[commit]**.

**2.2 API key.**
- Read the key from the environment variable `OPENALEX_API_KEY`. Pass it as the `api_key` query parameter.
- Never print, log, save, or commit the key. Any URL written to a log, manifest, fixture or report must have the `api_key` parameter removed. Add a unit test that checks this redaction.

**2.3 Data in git.**
- Add a `.gitignore` at the repository root excluding `data/`, `.venv/`, `__pycache__/` and `.pytest_cache/`.
- Commit code, config, tests (with key-free fixtures) and `reports/`. Do not commit `data/`.

**2.4 Platform.** Windows / PowerShell. The repo path contains a space (`GITHUB CODE`): use `pathlib` and quote paths in shell commands. Write all CSVs as UTF-8; release CSVs (those under `data/release/`) as `utf-8-sig` so they open correctly in Excel.

**2.5 Dependencies.** Python standard library plus `requests`, `pandas` and `pytest`. Create a dedicated virtual environment at `.venv/` in the repository root (git-ignored), using the same Python version the EPS project uses, and install the dependencies there. Record exact versions in `requirements.txt`. Do not install anything into the EPS environment or the global Python.

---

## 3. Fixed parameters

| Parameter | Value |
|---|---|
| Journal list | `config/journals.csv` (supplied; 20 rows — 19 candidate journals plus AEA Papers and Proceedings) |
| Years | Publication years **2016–2025 inclusive**, using OpenAlex `publication_year` |
| Journal filter | `primary_location.source.id:<source id>`, using the short id form (`S…`, with the `https://openalex.org/` prefix removed). See the Stage 0 probe for the diagnostic comparison with `locations.source.id` |
| Paging | Cursor paging: `cursor=*` on the first request, then `meta.next_cursor`; `per_page=100`; stop when `next_cursor` is null and `results` is empty |
| Fields | Save full records (do not use `select`) |
| Request timeout | 30 seconds |
| Retries | Up to 5 retries with exponential backoff (1, 2, 4, 8, 16 s) on HTTP 429, 403, ≥500 and timeouts. Other 4xx: do not retry; fail that request |
| Request rate | At most 5 requests per second |
| Budget guard | Before the full harvest, estimate the request count; **stop** if it exceeds 5,000 |
| Daily budget exhausted | If retries on 429/403 are exhausted, stop cleanly with the message "OpenAlex budget or rate limit reached — resume after midnight UTC". The harvest must be resumable (Stage 3) |

`config/journals.csv` columns: `journal_key, journal, issns, publisher, repec_rank, scimago_rank, in_top15_economics_only, in_top15_all_fields, role, notes`. `issns` is a `; `-separated list. Do not change the supplied rows. You may add an empty column `openalex_source_id_override` for manual corrections.

---

## 4. Package layout

```
Overton-Analysis/                    (repository root)
  OVERTON_STAGE1_BRIEF_v1.md        (this file — do not edit)
  .gitignore
  pyproject.toml                     (src layout; install into .venv with `pip install -e .`)
  requirements.txt
  README.md                          (short: purpose, setup, how to run each command)
  config/
    journals.csv                     (supplied)
    journals_resolved.csv            (Stage 2 output, committed)
  src/overton/
    __init__.py
    __main__.py                      (CLI entry: python -m overton <command>)
    settings.py                      (constants in section 3; YEARS, PER_PAGE, paths)
    client.py                        (HTTP session, api_key handling, redaction, retry/backoff, rate limit)
    resolve.py                       (journal -> OpenAlex source id)
    harvest.py                       (cursor paging, raw page storage, manifest, resume)
    normalise.py                     (raw pages -> works.csv, authorships.csv)
    filter_rules.py                  (rule definitions; FILTER_VERSION; rules_fingerprint())
    filter.py                        (applies rules -> include / exclusion_reason / review_flags)
    report.py                        (reports, review samples, release files, DOI batches)
  tests/
    fixtures/                        (real API responses from Stage 0, key removed)
    test_*.py
  data/                              (git-ignored)
    raw/openalex/<journal_key>/<year>/page_0001.json.gz
    interim/
    release/
    review/
  reports/
    harvest_manifest.csv
    harvest_report.csv
    STAGE1_RUN_REPORT.md
```

CLI commands: `resolve`, `harvest` (options `--pilot`, `--journals <keys>`, `--years <a-b>`), `normalise`, `filter`, `report`, and `all` (runs resolve → harvest → normalise → filter → report with the gates below). Each command reads only the files written by the previous command. `normalise`, `filter` and `report` make **no network calls**, so they can be re-run at any time without downloading again.

Follow the EPS convention for versioned rules: `filter_rules.py` holds `FILTER_VERSION = "F1"` and a `rules_fingerprint()` function (hash of the rule definitions), and both are written into the outputs.

---

## 5. Stages and gates

### Stage 0 — Preflight and API probe (read-only except fixtures)

0.1 Confirm the repository root (2.1), that the repository has at least one commit, and that the working tree is clean (`git status --porcelain` empty). If not clean, **stop** — do not commit changes you did not make.

0.2 Read (do not change) the EPS project's Python version. Create `.venv/` with that version and install `requests`, `pandas`, `pytest`. Report the Python and package versions.

0.3 Check `OPENALEX_API_KEY` is set — print only "set" or "not set". Call `https://api.openalex.org/rate-limit?api_key=…` and report the remaining daily allowance (no key in output). **Gate:** key set and accepted; otherwise stop.

0.4 Probe requests (save each response, key removed, to `tests/fixtures/`):
- (a) `GET /sources?filter=issn:0002-8282` (American Economic Review)
- (b) `GET /works?filter=primary_location.source.id:<AER id>,publication_year:2020&per_page=5`
- (c) the same as (b) with `locations.source.id` in place of `primary_location.source.id` — record both `meta.count` values
- (d) `GET /works?filter=primary_location.source.id:<AER id>,publication_year:2016-2025&per_page=1` — check whether the year-range syntax works by comparing `meta.count` with the sum of per-year counts. Use whichever form is proven; per-year requests are acceptable regardless, since the harvest runs per journal-year.

0.5 Check every Work field listed in Appendix A as "source field" exists in the probe responses under the stated name. **Gate:** if any field the normaliser depends on is missing or renamed, stop and report the actual structure. Do not guess field names.

### Stage 1 — Build the package and offline tests  **[commit]**

Build the layout in section 4. Tests (pytest, no network) must cover at least:
- abstract reconstruction from `abstract_inverted_index` (including null, empty, and repeated words at several positions);
- DOI normalisation (`https://doi.org/10.1257/AER.123` → `10.1257/aer.123`; null stays null);
- API key redaction from URLs;
- each filter rule, using synthetic titles (one positive and one negative case per rule);
- harvest resume logic (complete journal-years skipped; incomplete ones cleared and redone), using a fake client;
- normalisation of the Stage 0 fixture (b) into the Appendix A columns.

**Gate:** all tests pass.

### Stage 2 — Resolve journals to OpenAlex sources  **[commit]**

For each row of `journals.csv` (honour `openalex_source_id_override` if filled):
1. Query `/sources?filter=issn:<ISSN>` for every ISSN listed. Collect the distinct source ids returned.
2. If exactly one distinct source id, and its `type` is `journal`, status `ok`.
3. If none: search `/sources?search=<journal title>`, record up to 3 candidates (id, display_name, issn_l, works_count), status `not_found`.
4. If more than one: record all, status `ambiguous`.
5. For `ok` rows, also compute the similarity between our title and `display_name` (`difflib.SequenceMatcher` ratio); below 0.8 → status `name_mismatch`.

Write `config/journals_resolved.csv` with: `journal_key, journal, issns, openalex_source_id, openalex_display_name, openalex_issn_l, openalex_issns, openalex_type, openalex_works_count, openalex_host_organization, match_method, status, candidates`.

Check that AER and AEA Papers and Proceedings resolve to **different** source ids.

**Gate:** every row has status `ok`. Otherwise stop and print the problem rows with candidates. (The fix is a manual entry in `openalex_source_id_override`; do not choose for the user.)

### Stage 3 — Pilot harvest

Harvest `aer` and `qje` for years 2019 and 2020 (four journal-years).

For each (journal, year):
- Request the first page; record `meta.count` as `expected_count`. Page with the cursor to the end. Save every page, unchanged, as gzip-compressed JSON: `data/raw/openalex/<journal_key>/<year>/page_0001.json.gz`, `page_0002…`.
- Also request the count for the same journal-year using `locations.source.id` (one request, `per_page=1`) and record it as `locations_count` (diagnostic only; do not harvest it).
- Append one row to `reports/harvest_manifest.csv`: `journal_key, source_id, year, filter (key removed), expected_count, retrieved_count, unique_work_ids, n_pages, locations_count, status, started_at, finished_at, error`.
- `status` is `complete` only if `retrieved_count == expected_count == unique_work_ids`.
- Resume rule: on re-run, skip journal-years marked `complete` whose page files exist; for any other status, delete that journal-year's page files and redo it from the start.
- If counts do not match, retry that journal-year once from scratch. If they still do not match, mark `count_mismatch` and continue to the next journal-year.

**Gate:** all four pilot journal-years `complete`. Otherwise stop and report.

### Stage 4 — Full harvest  **[commit]**

1. Count first: for every (journal, year), get `meta.count` (one `per_page=1` request each). Estimated requests = Σ ceil(count / 100) + 2 × (number of journal-years). Report the estimate. **Gate:** ≤ 5,000, else stop.
2. Harvest all 20 journals × 2016–2025 (200 journal-years), reusing pilot results under the resume rule.

**Gate:** every journal-year `complete`. A journal-year with `expected_count == 0` is allowed (e.g. AEA Papers and Proceedings before 2018) but must be listed in the run report. Any `count_mismatch` or failure → stop and report.

### Stage 5 — Normalise (no network)

Read every raw page and write:
- `data/interim/works.csv` — one row per work, columns in Appendix A.1.
- `data/interim/authorships.csv` — one row per work × author × institution (an author with no institution gets one row with institution fields empty), columns in Appendix A.2.

Rules:
- **Abstract reconstruction:** place each word at each of its positions, order by position, join with single spaces, strip. Null or empty index → empty abstract and `has_abstract = False`.
- **DOI:** lowercase, strip the `https://doi.org/` prefix.
- `abstract_mentions_jel` = abstract matches `\bJEL\b` (case-sensitive).
- `page_count` = `last_page − first_page + 1` when both are integers, else empty.
- `cited_by_count` is a snapshot: record `harvest_date` with it.

**Gate:** `works.csv` row count equals the sum of `retrieved_count` in the manifest; no duplicate `openalex_id`. Duplicate DOIs (two works sharing one DOI) are not fatal: list them in the run report.

### Stage 6 — Filter: research papers vs other items (no network)  **[commit]**

Implement the rules in `filter_rules.py` (`FILTER_VERSION = "F1"`). Apply in order; the **first** matching exclusion rule sets `exclusion_reason`. Review flags never exclude; they mark items for a human to look at.

**Principle: prefer missing an exclusion to wrongly excluding a research paper.** Many research titles begin with words such as "Index", "Announcement", "Annual report", "Election of" or "Response to". Anything uncertain becomes a review flag, not an exclusion.

**Matching conventions.** Case-insensitive; title stripped of leading/trailing whitespace and trailing punctuation; curly quotes and dashes normalised. **(=)** means the whole title equals the phrase. **(^)** means the title starts with the phrase followed by a word boundary. **($)** means the title ends with the phrase. Where ":" appears in a pattern, also accept "—", "–" or " - ".

**Exclusion rules**

| Code | Rule |
|---|---|
| `E_TYPE` | OpenAlex `type` not in {`article`, `review`} (reason records the type, e.g. `E_TYPE:erratum`) |
| `E_PARATEXT` | `is_paratext` is true |
| `E_CORRECTION` | contains the whole word erratum, errata, corrigendum or corrigenda; or (^) "correction to", "correction:", "corrections to", "retraction notice", "retraction of", "retraction:", "expression of concern"; or (=) "correction", "corrections", "retraction" |
| `E_COMMENT` | (^) "comment on", "comments on", "a comment on", "comment:", "reply to", "a reply to", "reply:", "rejoinder"; or (=) "comment", "comments", "reply", "rejoinder"; or ($) ": comment", ": comments", ": reply", ": rejoinder", ": a comment", ": a reply", ": comment and reply" |
| `E_FRONTMATTER` | (=) "front matter", "back matter", "issue information", "table of contents", "contents", "index", "volume information", "masthead", "editorial board", "cover", "front cover", "back cover"; or (^) "front matter", "back matter", "issue information", "table of contents", "index to volume", "author index", "subject index", "volume information" |
| `E_ADMIN` | (^) "report of the editor", "report of the secretary", "report of the treasurer", "report of the president", "report of the committee", "minutes of the", "annual report of the", "news notes", "submission of manuscripts", "forthcoming papers", "forthcoming articles", "acknowledgment to", "acknowledgement to", "acknowledgments to", "list of referees", "referees for volume", "call for papers", "election of fellows", "election of officers", "fellows of the econometric society", "in memoriam", "obituary", "editor's note", "editors' note", "editorial note", "editorial:"; or (=) "announcement", "announcements", "editorial", "acknowledgments", "acknowledgements", "referees" |
| `E_BOOKS` | (^) "book review", "book reviews", "annotated listing of new books", "new books", "recent dissertations"; or (=) "dissertations" |
| `E_READING` | (^) "recommendations for further reading"; or (=) "correspondence" |

The filter tests must include these **negative** cases, none of which may be excluded: "Index Insurance and Farmer Welfare", "Announcement Effects of Monetary Policy", "Annual Report Readability and Investment Efficiency", "Election of Women and Local Public Spending", "Response to Monetary Policy Shocks across Firms", "Correction of Measurement Error in Survey Income", "Cover Crops and Farm Profits", "Editorial Boards and Publication Bias".

**Review flags** (semicolon-separated in `review_flags`)

| Code | Rule |
|---|---|
| `F_SHORT` | `page_count` ≤ 3 |
| `F_NO_AUTHORS` | no authorships |
| `F_NO_ABSTRACT_NO_DOI` | no abstract and no DOI |
| `F_RETRACTED` | `is_retracted` is true |
| `F_COMMENT_WORD` | title contains "comment", "reply", "rejoinder" or starts with "response to", but no exclusion rule matched |
| `F_ADMIN_WORD` | title starts with "report", "announcement", "index", "editorial" or "correction", but no exclusion rule matched |
| `F_JEL_NO_ABSTRACT` | journal is `jel` and no abstract (likely a book review) |
| `F_INTRO` | title starts with "introduction to", "symposium", "introduction:" or "foreword" |

Write `data/interim/works_filtered.csv` (= works.csv + `include`, `exclusion_reason`, `review_flags`, `filter_version`, `rules_fingerprint`).

**Gate:** none fatal. Report counts by rule and by journal.

### Stage 7 — Release files, review samples and run report (no network)  **[commit]**

Write to `data/release/`:
- `papers_stage1.csv` — included works only; Appendix A.1 columns plus `journal_key, in_top15_economics_only, in_top15_all_fields, filter_version, rules_fingerprint`.
- `authorships_stage1.csv` — authorship rows for included works.
- `excluded_items.csv` — excluded works with `exclusion_reason`.
- `overton_doi_batch_01.txt`, `_02.txt`, … — DOIs of included works, deduplicated, lowercase, one per line, at most 25,000 per file.

Write to `data/review/` (random draws use seed `20261012`):
- `journals_resolved_review.csv` — copy of `config/journals_resolved.csv`.
- `sample_included.csv` — 50 random included works (`journal_key, year, title, openalex_type, page_count, doi, review_flags`).
- `sample_excluded.csv` — up to 50 excluded works, stratified across `exclusion_reason` (all of them if fewer than 50).
- `flagged.csv` — every included work with at least one review flag.

Write to `reports/`:
- `harvest_report.csv` — one row per journal-year: `expected_count, retrieved_count, locations_count, included, excluded` (plus one column per exclusion rule), `flagged, pct_with_doi, pct_with_abstract, pct_with_any_institution, n_abstract_mentions_jel` (all percentages over included works).
- `STAGE1_RUN_REPORT.md` — a factual run log, no interpretation beyond the numbers:
  1. run date, git commit, `FILTER_VERSION` and fingerprint, OpenAlex allowance used;
  2. totals: works harvested, included, excluded by rule, flagged;
  3. table by journal (all years pooled): included, % with abstract, % with DOI;
  4. journal-years where `locations_count` differs from `expected_count` (with both numbers);
  5. journal-years with zero works;
  6. duplicate DOIs, if any;
  7. number of included abstracts containing "JEL";
  8. any deviation from this brief, and why.

---

## 6. Stop conditions (summary)

Stop and report — do not work around — if any of these occur:
1. Repository root differs from 2.1, or the working tree is not clean at start.
2. API key not set or rejected.
3. A Work field in Appendix A is missing or renamed in the probe.
4. Any test fails.
5. Any journal resolves to a status other than `ok`.
6. A pilot journal-year is not `complete`.
7. The request estimate exceeds 5,000.
8. A full-harvest journal-year ends in `count_mismatch` or failure.
9. OpenAlex budget or rate limit reached (stop cleanly; the run is resumable).
10. `works.csv` row count does not equal the manifest total, or duplicate `openalex_id`s exist.
11. The virtual environment cannot be created or the dependencies cannot be installed into it.

When finished (or stopped), give a short summary: stages completed, gates passed, headline counts, the location of the review files, and anything that needs a human decision.

---

## Appendix A — Output schemas

### A.1 `works.csv`

| Column | Source field (OpenAlex Work) | Notes |
|---|---|---|
| `openalex_id` | `id` | |
| `doi` | `doi` | normalised (lowercase, no prefix) |
| `title` | `title` | |
| `publication_year` | `publication_year` | |
| `publication_date` | `publication_date` | |
| `journal_key` | — | from the journal being harvested |
| `source_id` | `primary_location.source.id` | |
| `source_display_name` | `primary_location.source.display_name` | |
| `volume`, `issue`, `first_page`, `last_page` | `biblio.*` | |
| `page_count` | derived | see Stage 5 |
| `openalex_type` | `type` | |
| `is_paratext` | `is_paratext` | |
| `is_retracted` | `is_retracted` | |
| `language` | `language` | |
| `abstract` | `abstract_inverted_index` | reconstructed |
| `has_abstract` | derived | |
| `abstract_word_count` | derived | |
| `abstract_mentions_jel` | derived | |
| `n_authors` | `authorships` | count |
| `n_institutions` | `authorships[].institutions[].id` | distinct count |
| `n_countries` | `authorships[].countries` | distinct count |
| `cited_by_count` | `cited_by_count` | snapshot |
| `fwci` | `fwci` | |
| `referenced_works_count` | `referenced_works_count` | |
| `primary_topic`, `primary_subfield`, `primary_field`, `primary_domain` | `primary_topic.display_name`, `.subfield.display_name`, `.field.display_name`, `.domain.display_name` | |
| `keywords` | `keywords[].display_name` | `; `-separated |
| `is_oa`, `oa_status` | `open_access.is_oa`, `open_access.oa_status` | |
| `harvest_date` | — | date of the harvest run |
| `raw_file` | — | relative path of the page file the record came from |

### A.2 `authorships.csv`

| Column | Source field |
|---|---|
| `openalex_id` | work `id` |
| `author_order` | position in `authorships` (1-based) |
| `author_position` | `authorships[].author_position` |
| `author_id`, `author_name`, `orcid` | `authorships[].author.id`, `.display_name`, `.orcid` |
| `is_corresponding` | `authorships[].is_corresponding` |
| `institution_id`, `institution_name`, `institution_ror`, `institution_country`, `institution_type` | `authorships[].institutions[].id`, `.display_name`, `.ror`, `.country_code`, `.type` |
| `raw_affiliation_strings` | `authorships[].raw_affiliation_strings` (`; `-separated) |

Note: OpenAlex lists at most the first 100 authors per work. Record in the run report any work with exactly 100 authorships.
