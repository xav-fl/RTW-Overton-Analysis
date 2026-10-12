# Overton Analysis — Stage 1

Downloads journal articles for 20 economics journals (publication years 2016–2025)
from the OpenAlex API, separates research papers from comments, corrections,
front matter and other non-research items, and writes paper and author tables
plus DOI lists for upload to Overton. The full specification is in
[OVERTON_STAGE1_BRIEF_v1.md](OVERTON_STAGE1_BRIEF_v1.md).

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

`data/` is git-ignored.
