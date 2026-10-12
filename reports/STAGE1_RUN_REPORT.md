# Stage 1 run report

## 1. Run

- Report generated: 2026-10-12 21:20 UTC
- Harvest dates: 2026-10-12
- Git commit: `25be570`
- Filter: `F2`, rules fingerprint `4eadf77b36ca`
- OpenAlex usage logged across networked commands: 728 successful requests, $0.0728 of the daily allowance (remaining after last command: $0.9252; resets 2026-10-13T00:00:00.000Z)

  - 2026-10-12T21:06:47Z `resolve`: 35 requests (35 attempts incl. retries)
  - 2026-10-12T21:07:02Z `harvest --pilot`: 10 requests (10 attempts incl. retries)
  - 2026-10-12T21:14:04Z `harvest`: 683 requests (683 attempts incl. retries)

## 2. Totals

- Works harvested: 19189
- Included: 16147
- Excluded: 3042
- Included works with at least one review flag: 2240
- DOIs in Overton batches: 16109 in 1 file(s)

Excluded by reason:

| reason | n |
|---|---|
| E_TYPE:paratext | 1273 |
| E_MISDATED | 673 |
| E_COMMENT | 294 |
| E_TYPE:book-review | 206 |
| E_ADMIN | 199 |
| E_TYPE:erratum | 125 |
| E_TYPE:editorial | 99 |
| E_BOOKS | 40 |
| E_READING | 39 |
| E_NONENGLISH_NO_DOI | 35 |
| E_TYPE:letter | 33 |
| E_FRONTMATTER | 11 |
| E_TYPE:retraction | 6 |
| E_CORRECTION | 5 |
| E_TYPE:other | 4 |

Review flags on included works:

| flag | n |
|---|---|
| F_SHORT | 1800 |
| F_NO_AUTHORS | 583 |
| F_ADMIN_WORD | 63 |
| F_JEL_NO_ABSTRACT | 43 |
| F_NO_ABSTRACT_NO_DOI | 37 |
| F_INTRO | 31 |
| F_COMMENT_WORD | 14 |
| F_RETRACTED | 8 |

## 3. By journal (all years pooled)

| journal_key | harvested | included | pct_with_abstract | pct_with_doi |
|---|---|---|---|---|
| ecta | 995 | 734 | 85.7 | 100.0 |
| aer | 2351 | 1415 | 97.2 | 99.9 |
| qje | 486 | 464 | 96.8 | 100.0 |
| jel | 755 | 457 | 90.6 | 99.8 |
| aej_macro | 452 | 411 | 100.0 | 100.0 |
| jpe | 1182 | 989 | 81.4 | 99.9 |
| restud | 897 | 866 | 96.8 | 100.0 |
| jep | 498 | 413 | 99.5 | 100.0 |
| aej_applied | 506 | 461 | 100.0 | 100.0 |
| joe | 1808 | 1664 | 19.4 | 100.0 |
| jme | 1003 | 803 | 22.5 | 100.0 |
| arecon | 284 | 273 | 100.0 | 100.0 |
| restat | 1106 | 1101 | 94.9 | 99.9 |
| jole | 593 | 535 | 81.7 | 97.6 |
| jeea | 643 | 620 | 94.4 | 99.7 |
| rfs | 1236 | 1172 | 89.6 | 99.8 |
| jfe | 1550 | 1380 | 17.0 | 99.1 |
| jf | 1098 | 856 | 77.2 | 99.8 |
| jae | 570 | 456 | 12.7 | 99.6 |
| aea_pp | 1176 | 1077 | 89.7 | 99.9 |

## 4. Journal-years where locations_count differs from expected_count

| journal_key | year | expected_count | locations_count |
|---|---|---|---|
| aej_macro | 2021 | 43 | 44 |
| aer | 2016 | 1032 | 1048 |
| aer | 2017 | 282 | 285 |
| aer | 2018 | 127 | 129 |
| aer | 2022 | 125 | 126 |
| aer | 2025 | 129 | 131 |
| ecta | 2018 | 94 | 96 |
| jeea | 2019 | 84 | 85 |
| jeea | 2023 | 72 | 73 |
| jel | 2016 | 126 | 132 |
| jel | 2017 | 87 | 88 |
| jel | 2018 | 72 | 73 |
| jel | 2019 | 67 | 68 |
| jep | 2017 | 52 | 53 |
| jep | 2018 | 54 | 55 |
| jfe | 2016 | 183 | 184 |
| jfe | 2019 | 160 | 161 |
| jfe | 2020 | 164 | 165 |
| joe | 2016 | 153 | 154 |
| joe | 2018 | 177 | 180 |
| joe | 2020 | 272 | 273 |
| joe | 2021 | 182 | 183 |
| jole | 2018 | 32 | 33 |
| jole | 2022 | 69 | 70 |
| jpe | 2016 | 70 | 73 |
| jpe | 2017 | 115 | 122 |
| jpe | 2018 | 137 | 143 |
| jpe | 2019 | 100 | 103 |
| jpe | 2021 | 113 | 114 |
| qje | 2019 | 43 | 44 |
| restat | 2018 | 104 | 105 |
| restat | 2020 | 126 | 127 |

## 5. Journal-years with zero works

| journal_key | year |
|---|---|
| aea_pp | 2016 |
| aea_pp | 2017 |

## 6. Duplicate DOIs (two or more works sharing one DOI)

(none)

## 7. Included abstracts containing "JEL"

2165 of 16147 included works (of which 11607 have an abstract).

Works with exactly 100 authorships (OpenAlex truncation limit): 1: https://openalex.org/W4394881644

## 8. Deviations from the brief

- The repository was created empty on GitHub (RTW-Overton-Analysis) and cloned to `GITHUB CODE/Overton-Analysis`; at the user's request Claude made the initial commit (the brief and `config/journals.csv`) so that the Stage 0 preflight could pass.
- Dropped connections (`ConnectionError`, e.g. WinError 10054 connection resets, seen repeatedly on this network) are retried with the same backoff as timeouts. The brief lists timeouts only; a reset connection is the same transient failure.
- The rate limiter spaces requests at least 0.2 s apart (5/s), counting retries.
- The empty terminal page of each cursor walk (results empty, next_cursor null) is requested but not saved; `n_pages` counts saved pages with results.
- The manifest is append-only (one row per attempt); the latest row per journal-year is that journal-year's state.
- A resolved source whose `type` is not `journal` gets status `not_journal` (the brief names no status for this case; any non-`ok` status fails the gate).
- OpenAlex's `/rate-limit` echoes a masked form of the key; the client drops that field and stores only the `rate_limit` block.
- Filter F2 (added after reviewing the F1 run, at the user's request) adds two exclusion rules applied after the F1 rules, both limited to works without a DOI: `E_MISDATED` (numeric volume more than 1 below the lowest volume among DOI-bearing works of the same journal-year; catches legacy records of 1969-1998 AER/JEL papers that OpenAlex dates 2016-01-01) and `E_NONENGLISH_NO_DOI` (language set and not English; catches Japanese steel-engineering papers attached to the Journal of Financial Economics source). Neither rule is in the brief.
