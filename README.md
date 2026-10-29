# Overton Analysis

Which economics research gets cited in policy documents? This repository
collects every research paper published in 20 economics journals from 2016 to
2025, codes each one's characteristics (topic, JEL codes, research design,
policy relevance, readability), and counts the policy documents that cite it,
using Overton. It is one half of a study comparing what economists research
with what policymakers say they care about. The other half, policymakers'
statements, is in [RTW-Speech-Scanner-V1](https://github.com/xav-fl/RTW-Speech-Scanner-V1).

## Start here: the data

All outputs are in [`data/release/`](data/release).

| File | Rows | What it is |
|---|---|---|
| **`papers_coded_cited.csv`** | 16,147 | **The main table.** One row per research paper: OpenAlex metadata, the LLM-coded characteristics and the policy-citation counts. Coding and citation counts are filled in for the papers done so far (195 coded, 100 matched against Overton) and blank for the rest |
| **`overton_sample_merged_v0.2.xlsx`** | 100 | **The easiest place to start.** The 100-paper pilot sample in Excel, with a "Read me" sheet: paper metadata, coding and citations, plus sheets for authors, citations by characteristic, every citing document and every citing source |
| `overton_coded_sample_v0.2.xlsx`, `…_cited.xlsx` | 100 | Earlier cuts of the same pilot workbook: coding only, then coding plus citations |
| `policy_citation_links.csv` | 1,653 | One row per paper × citing policy document, with whether it counted towards the total and why |
| `overton_sources.csv` | 234 | Each citing organisation and how many of its documents were counted or excluded, for reviewing the inclusion rule |
| `papers_stage1.csv` | 16,147 | Research papers before coding (OpenAlex metadata only) |
| `authorships_stage1.csv` | | Paper × author × institution |
| `author_disciplines.csv` | 487 | Each author's department discipline, coded from the affiliation text |
| `excluded_items.csv` | 3,042 | Journal items that are not research papers (comments, corrections, front matter …), with the reason |
| `overton_doi_*.txt` | | DOI lists to upload to Overton |

Every column of `papers_coded_cited.csv` is defined in
[`DATA_DICTIONARY.md`](DATA_DICTIONARY.md). The coding rules are in [`config/llm_codebook_v0.2.txt`](config/llm_codebook_v0.2.txt).
[`reports/`](reports) holds the run reports, and `data/review/` holds the
samples set aside for human checking.

## Pipeline

| Stage | What it does | Command |
|---|---|---|
| 1 | Harvest the journals from OpenAlex and filter out non-research items | `overton all` |
| 2 | Code each paper with Claude against the codebook | `overton llm-run`, `llm-assemble` |
| 3 | Merge in the policy documents that cite each paper, exported from Overton | `overton overton-merge` |

The full Stage 1 specification is in
[OVERTON_STAGE1_BRIEF_v1.md](OVERTON_STAGE1_BRIEF_v1.md). The rest of this
README is the reference for running each stage.

## Setup (Windows / PowerShell)

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pip install -e .
$env:OPENALEX_API_KEY = "<your key>"     # never commit or print it
```

## Commands

```powershell
.venv\Scripts\python -m overton resolve      # journals -> OpenAlex source ids (config/journals_resolved.csv)
.venv\Scripts\python -m overton harvest --pilot                    # aer + qje, 2019-2020
.venv\Scripts\python -m overton harvest                            # all journals, 2016-2025 (resumable)
.venv\Scripts\python -m overton harvest --journals aer,qje --years 2016-2018
.venv\Scripts\python -m overton normalise    # raw pages -> data/interim/works.csv, authorships.csv
.venv\Scripts\python -m overton filter       # -> data/interim/works_filtered.csv
.venv\Scripts\python -m overton report       # -> data/release/, data/review/, reports/
.venv\Scripts\python -m overton all          # everything above, stopping at any failed gate
.venv\Scripts\python -m pytest               # offline tests
```

`normalise`, `filter` and `report` make no network calls. Exit code 2 means a
gate failed; 3 means the OpenAlex daily budget or rate limit was reached — re-run
the same command after midnight UTC and the harvest resumes where it stopped.

## Outputs

| Path | Contents |
|---|---|
| `data/raw/openalex/<journal>/<year>/page_NNNN.json.gz` | API responses, unchanged |
| `reports/harvest_manifest.csv` | one row per harvest attempt per journal-year |
| `data/release/papers_stage1.csv` | included research papers |
| `data/release/authorships_stage1.csv` | paper × author × institution |
| `data/release/excluded_items.csv` | excluded items with reason |
| `data/release/overton_doi_batch_NN.txt` | DOIs for Overton, ≤ 25,000 per file |
| `data/review/` | samples and flagged items for human review |
| `reports/STAGE1_RUN_REPORT.md`, `reports/harvest_report.csv` | run log and per journal-year counts |

`data/raw/openalex/` and the `data/interim/` tables are not committed, because
the commands above rebuild them. Everything that can't be rebuilt by code is
committed: `data/release/`, `data/review/`, the Overton exports in
`data/raw/overton/`, and the model responses in `data/interim/llm/`.

# Stage 2 — LLM-coded paper characteristics

Codes each paper in `papers_stage1.csv` with Claude (`claude-opus-5-5`, adaptive
thinking, effort `medium`): one request per paper, answers constrained to a JSON
schema. The codebook the model follows is
[config/llm_codebook_v0.2.txt](config/llm_codebook_v0.2.txt) — a draft for review;
edit it, bump `LLM_CODEBOOK_VERSION` in `settings.py`, and the next run codes under
a new run key without overwriting earlier answers. JEL codes come from
`config/jel_taxonomy_compact.txt` (shared with the speeches project).

| Field (in `papers_coded.csv`) | Source |
|---|---|
| `llm_topic_label`, `llm_jel_codes`, `llm_jel_primary`, `llm_jel_primary_major` | model (OpenAlex has no JEL codes) |
| `jel_codes_author` | parsed from abstracts that list them (2,164 papers); removed before coding, then compared: `llm_jel_overlaps_author` |
| `llm_cat_*` (8 survey categories, yes/no each), `llm_primary_policy_category` | model |
| `llm_item_type`, `llm_research_type`, `llm_empirical_design`, `llm_is_review`, `llm_is_empirical`, `llm_causal_design` | model |
| `llm_policy_evaluation`: a causal-effect or unintended-consequences category, with an experimental, quasi-experimental or structural design | computed from the model's fields |
| `llm_policy_reference` (none / existing / proposed / both) | model |
| `llm_jargon`, `llm_sentence_complexity` (1–5) | model |
| `abs_flesch_reading_ease`, `abs_flesch_kincaid_grade`, `abs_words_per_sentence`, … | computed in code |
| `multidisciplinary`, `multidisciplinary_beyond_econ_business`, `n_distinct_disciplines` | model codes each author's department from the affiliation text (`author_disciplines.csv`) |

Papers without a usable abstract (under 30 words; 28% of papers, mostly JAE,
JFE, JME, JoE) are still sent, for topic, JEL and author disciplines; their
abstract-based fields are left blank (`llm_coded_from = title_only`).

### Through Claude Code (default; no API key)

`llm-run` calls the Claude Code CLI (`claude -p`) under your own Claude sign-in,
in the same way the speeches bundle calls `codex exec`. Each call runs from an
empty temporary folder with no tools, MCP servers, settings files or saved
session, takes the codebook as its whole system prompt, and must answer in the
same JSON schema as the API route. The CLI is found on PATH, or else as the copy
the Claude desktop app installs; set `CLAUDE_CODE_EXE` to point at another.
Sign in once (the CLI keeps its own sign-in, separate from the desktop app's):

```powershell
claude auth login          # or: & "$env:LOCALAPPDATA\Claude-Data\...\claude.exe" auth login
.venv\Scripts\python -m overton llm-sample                 # 100-paper validation sample -> data/review/
.venv\Scripts\python -m overton llm-run --sample           # code the sample
.venv\Scripts\python -m overton llm-assemble               # -> data/release/papers_coded.csv, reports/LLM_CODING_REPORT.md
.venv\Scripts\python -m overton llm-compare --old <run key>   # after revising the codebook: what changed
.venv\Scripts\python -m overton llm-agreement --human data/review/llm_validation_sample_coded.csv
.venv\Scripts\python -m overton llm-run --all              # everything else (resumes if stopped)
.venv\Scripts\python -m overton llm-assemble
```

Calls count against your Claude plan's usage limits rather than being billed per
token; the token counts and API-price equivalent are still recorded. On a usage
limit or sign-in failure the run stops (exit code 4) and `llm-run --all` resumes
where it left off. `--workers` (default 4) sets how many calls run at once.

### Through the API

```powershell
$env:ANTHROPIC_API_KEY = "<your key>"                      # never commit or print it
.venv\Scripts\python -m overton llm-run --route api --sample   # full price; prints cost per paper
.venv\Scripts\python -m overton llm-submit --all           # Message Batches (half price)
.venv\Scripts\python -m overton llm-collect                # fetch finished batches (re-run until none in progress)
```

API requests opt into server-side refusal fallbacks (`fallbacks: "default"`),
which the Claude Code route does not have; `llm_answered_model` records which
model answered and `llm_route` which route.

Both routes write the same records and share a run key, so they can be mixed.
`llm-run` and `llm-submit` need `--limit N`, `--sample` or `--all`, and skip
papers already coded under the current run key, so both resume. `--model` and
`--effort` override the defaults (and change the run key). Every response is kept
in `data/interim/llm/responses.jsonl`. Exit code 4 means no further request can
succeed (credit, key, sign-in or usage limit).

# Stage 3 — policy citations from Overton

1. Search Overton's scholarly works with a DOI list (e.g. `data/release/overton_doi_sample_100.txt`)
   and export the **policy documents** citing them, with all columns, as CSV.
2. Save the export in `data/raw/overton/`, and a copy of the DOI list you searched in
   `data/raw/overton/queried/`. A searched paper with no citing document gets 0; a paper
   whose DOI is in no list there stays blank.
3. `.venv\Scripts\python -m overton overton-merge`

Which citing documents count: everything from government, IGO and legislative sources,
including their research working papers; think-tank and NGO documents except working
papers (Overton files NBER, IZA, ifo/CESifo and IFS working papers as think-tank
documents); never scholarly articles. A document listed twice (re-issued, or co-published
by two institutions) counts once per paper. `policy_cites_all` is the count before exclusions.

| Output | Contents |
|---|---|
| `data/release/papers_coded_cited.csv` | `papers_coded.csv` plus `policy_cites`, `policy_cited_any`, counts by organisation type and region, first citation year |
| `data/release/policy_citation_links.csv` | paper × citing document, with whether it counted and why |
| `data/release/overton_sources.csv` | each citing organisation: documents, counted, excluded — for reviewing the rule |
