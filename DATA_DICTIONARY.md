# Data dictionary: `data/release/papers_coded_cited.csv`

This file has one row per research paper (16,147 rows) and 108 columns. It is
`papers_coded.csv` with the Overton citation counts added.

Each column comes from one of three stages: Stage 1 (OpenAlex harvest and
filter), Stage 2 (LLM coding, plus features computed in code) or Stage 3
(Overton merge). The table entries say which. Definitions come from the code in
`src/overton/` and the coding rules in `config/llm_codebook_v0.2.txt`.

Lists inside a cell are separated by `; `, except `llm_problems`, which uses ` | `.

## Blank vs 0

- **Coding.** `llm_coded_from = not_coded` means the paper has not been coded
  yet, so all `llm_*` and discipline fields are blank. `title_only` means the
  paper was coded without a usable abstract. In that case `llm_research_type`,
  `llm_empirical_design`, `llm_cat_*`, `llm_primary_policy_category`,
  `llm_policy_reference`, `llm_jargon`, `llm_sentence_complexity`,
  `llm_is_review`, `llm_is_empirical`, `llm_causal_design` and
  `llm_policy_evaluation` are blank, and topic, JEL codes and author
  disciplines are still filled.
- **Citations.** `overton_queried = False` means the DOI has not been searched
  on Overton, so every `policy_*` column is blank. A searched paper with no
  citing document gets 0.

## 1. Bibliographic metadata (Stage 1, OpenAlex)

| Column | Meaning |
|---|---|
| `openalex_id` | OpenAlex Work ID (unique key) |
| `doi` | DOI, lowercased, without the `https://doi.org/` prefix (key for the Overton merge) |
| `title` | Title |
| `publication_year`, `publication_date` | As in OpenAlex |
| `journal_key` | Short journal code (e.g. `aer`, `ecta`), from `config/journals.csv` |
| `source_id`, `source_display_name` | OpenAlex source (journal) ID and name |
| `volume`, `issue`, `first_page`, `last_page` | OpenAlex `biblio` |
| `page_count` | `last_page − first_page + 1`; blank if either page is not an integer |
| `openalex_type` | OpenAlex work type |
| `is_paratext` | OpenAlex flag for front matter, tables of contents etc. |
| `is_retracted` | OpenAlex retraction flag |
| `language` | OpenAlex language code |
| `abstract` | Abstract rebuilt from OpenAlex's inverted index (raw, may include a JEL list) |
| `has_abstract` | `abstract` is non-empty |
| `abstract_word_count` | Words in `abstract` |
| `abstract_mentions_jel` | The raw abstract contains a JEL-code list |
| `n_authors` | Number of authorships (OpenAlex lists at most 100) |
| `n_institutions` | Distinct institution IDs across authors |
| `n_countries` | Distinct countries across authors |
| `cited_by_count` | Academic citations in OpenAlex at harvest (snapshot) |
| `fwci` | Field-weighted citation impact (1 = average for field, year and type) |
| `referenced_works_count` | Number of references |
| `primary_topic`, `primary_subfield`, `primary_field`, `primary_domain` | OpenAlex's own topic classification, not the LLM's |
| `keywords` | OpenAlex keywords |
| `is_oa`, `oa_status` | Open-access flag and status (gold, green, hybrid, bronze, diamond, closed) |
| `harvest_date` | Date of the harvest run |
| `raw_file` | Raw API page the record came from (`data/raw/openalex/…`, not committed) |

## 2. Sample and filter (Stage 1)

| Column | Meaning |
|---|---|
| `in_top15_economics_only`, `in_top15_all_fields` | Journal-level flags copied from `config/journals.csv` (top-15 status under two rankings; see that file's `repec_rank`, `scimago_rank` and `notes`) |
| `filter_version` | Version of the exclusion rules applied (e.g. `F2`) |
| `rules_fingerprint` | Hash of those rules, to show which exact rule set produced the file |

## 3. Abstract features (Stage 2, computed in code)

| Column | Meaning |
|---|---|
| `abstract_clean` | `abstract` with any JEL-code list removed; this is the text the model saw |
| `abstract_clean_word_count` | Words in `abstract_clean` |
| `has_usable_abstract` | `abstract_clean_word_count ≥ 30` |
| `abstract_suspect_long` | `abstract_clean_word_count > 500` (probably mis-scraped) |
| `jel_codes_author` | JEL codes the authors printed in the abstract |
| `n_jel_codes_author` | Number of those codes |
| `abs_n_sentences` | Sentences in `abstract_clean` |
| `abs_words_per_sentence` | Words ÷ sentences (WPS) |
| `abs_chars_per_word` | Mean word length in characters |
| `abs_share_polysyllabic` | Share of words with ≥ 3 syllables |
| `abs_flesch_reading_ease` | 206.835 − 1.015·WPS − 84.6·SPW, where SPW = syllables per word. Higher = easier |
| `abs_flesch_kincaid_grade` | 0.39·WPS + 11.8·SPW − 15.59. Higher = harder |

The readability columns are blank when `has_usable_abstract` is False.
Syllables are counted heuristically in `features.syllables`.

## 4. LLM coding (Stage 2)

Each paper is sent with its title, journal, clean abstract and authors'
affiliations. Fields marked *model* are the model's answers. Fields marked
*derived* are computed from those answers in `llm_assemble.py`.

| Column | Source | Meaning |
|---|---|---|
| `n_authors_sent` | code | Authors included in the request (first 40) |
| `llm_coded_from` | code | `abstract`, `title_only` or `not_coded` (see above) |
| `llm_item_type` | model | `research_article`, `review_article`, `non_research` |
| `llm_topic_label` | model | Plain-English topic, ≤ 8 words |
| `llm_jel_codes` | model | 1–3 three-character JEL codes, most central first |
| `llm_jel_primary` | derived | First code in `llm_jel_codes` |
| `llm_jel_primary_major` | derived | Its letter (major JEL field) |
| `llm_research_type` | model | `theoretical`, `empirical`, `theory_and_empirical`, `econometric_methods`, `review_or_synthesis`, `other` |
| `llm_empirical_design` | model | `experimental`, `quasi_experimental`, `structural`, `descriptive_or_correlational`, `forecasting_or_calibration`, `not_empirical` |
| `llm_cat_proposes_novel_policy`, `llm_cat_causal_effect_of_policy`, `llm_cat_descriptive_fact`, `llm_cat_unintended_consequences`, `llm_cat_predicts_effects_with_models`, `llm_cat_cost_benefit_or_welfare`, `llm_cat_identifies_mechanisms`, `llm_cat_impacts_on_specific_groups` | model | Eight yes/no policy categories from the policymaker survey, each independent, so a paper can be yes on several or none. Definitions in codebook item 6 |
| `llm_n_policy_categories` | derived | Number of `llm_cat_*` that are True |
| `llm_primary_policy_category` | model | The single best category (one answered yes), or `none` |
| `llm_policy_reference` | model | `none`, `existing_policy`, `proposed_or_hypothetical_policy`, `both` |
| `llm_jargon` | model | 1 (plain) to 5 (very technical) |
| `llm_sentence_complexity` | model | 1 (simple) to 5 (convoluted) |
| `llm_is_review` | derived | `llm_item_type = review_article` **or** `llm_research_type = review_or_synthesis` |
| `llm_is_empirical` | derived | `llm_research_type` is `empirical` or `theory_and_empirical` |
| `llm_causal_design` | derived | `llm_empirical_design` is `experimental` or `quasi_experimental` (**excludes** structural) |
| `llm_policy_evaluation` | derived | (`llm_cat_causal_effect_of_policy` or `llm_cat_unintended_consequences`) **and** design is `experimental`, `quasi_experimental` or `structural` (**includes** structural) |
| `llm_notes` | model | The model's note on anything uncertain |
| `llm_problems` | code | Validation failures in the answer (e.g. invalid JEL code, wrong number of authors). Blank = passed |
| `llm_answered_model` | code | Model that answered (differs from the requested model if an API fallback answered) |
| `llm_route` | code | `claude-code` (CLI) or `api` |
| `llm_codebook_version` | code | Codebook version used (e.g. `v0.2`) |
| `llm_run_key` | code | Hash of codebook + taxonomy, model and effort. Identifies the coding run |

### JEL agreement (derived; blank unless the authors listed JEL codes)

| Column | Meaning |
|---|---|
| `llm_jel_overlaps_author` | Some model code equals some author code truncated to 3 characters |
| `llm_jel_primary_major_in_author` | The letter of the model's primary code is among the letters of the authors' codes |

### Author disciplines (model codes each author; summaries derived)

The model codes each author's department from the affiliation text, as one of:
`economics`, `finance_accounting`, `business_management`,
`political_science_public_policy`, `sociology_demography`,
`psychology_behavioral`, `law`, `statistics_mathematics`,
`computer_science_engineering`, `medicine_public_health`,
`natural_environmental_science`, `other`, `unknown`. Per-author rows are in
`author_disciplines.csv`.

| Column | Meaning |
|---|---|
| `author_disciplines` | One discipline per author, in author order |
| `n_distinct_disciplines` | Distinct known disciplines (excluding `unknown`) |
| `share_authors_unknown_discipline` | Share of authors coded `unknown` |
| `multidisciplinary` | ≥ 2 distinct known disciplines. Blank if every author is `unknown` |
| `multidisciplinary_beyond_econ_business` | As above, with economics, finance_accounting and business_management treated as one discipline |
| `any_author_outside_econ_business` | Some known discipline is outside those three. Blank if every author is `unknown` |

## 5. Policy citations (Stage 3, Overton)

**Counted:** every document from government, IGO and legislative sources,
including their working papers, and think-tank and NGO documents except
working papers. Overton files NBER, IZA, ifo/CESifo and IFS working papers as
think-tank documents, so those are excluded.

**Never counted:** scholarly articles.

A document listed twice for the same paper (same title) counts once. The
document-level detail is in `policy_citation_links.csv`.

| Column | Meaning |
|---|---|
| `overton_queried` | The DOI was in a list searched on Overton (`data/raw/overton/queried/`) |
| `policy_cites` | **Main measure.** Counted citing documents |
| `policy_cited_any` | `policy_cites > 0` |
| `policy_cites_all` | Citing documents before the inclusion rule (after de-duplication) |
| `policy_cites_excluded` | `policy_cites_all − policy_cites` |
| `policy_cites_government`, `policy_cites_igo`, `policy_cites_legislative` | Counted documents by Overton organisation type: Government, IGO, Legislative Body |
| `policy_cites_think_tank_ngo` | Counted documents from Think Tank or NGO sources |
| `policy_cites_us` | Counted documents whose source country is USA |
| `policy_cites_europe` | Source country in Europe (EU bodies, UK, EEA, Switzerland and EU member states; list in `policy_cites.EUROPE`) |
| `policy_cites_international` | Overton source country is `IGO` (e.g. World Bank, IMF, OECD) |
| `policy_cites_other_region` | Any other country |
| `policy_cites_n_sources` | Distinct citing organisations among counted documents |
| `policy_first_cite_year` | Year of the earliest counted citing document |
| `policy_years_to_first_cite` | `policy_first_cite_year − publication_year` |

Type and region splits each sum to `policy_cites`.
