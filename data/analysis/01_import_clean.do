/*==============================================================================
  01_import_clean.do
  Import the merged Overton sample (paper-level, sheet "Merged sample") and
  do basic cleaning: short variable names, Yes/No -> 0/1, labelled categoricals,
  dates, ID checks and internal consistency checks.

  Input : release/overton_sample_merged_v0.2.xlsx   (sheet "Merged sample")
  Output: analysis/output/overton_sample_clean.dta
          analysis/output/01_import_clean.log

  Paths are relative to the data folder. Set $overton_data before running
  if your copy lives elsewhere.
==============================================================================*/

version 17
clear all
set more off

if "$overton_data" == "" global overton_data "C:/Users/u2272618/GitHub/RTW-Overton-Analysis/data"
cd "$overton_data"

capture mkdir "analysis/output"
capture log close
log using "analysis/output/01_import_clean.log", replace text

local xlsx  "release/overton_sample_merged_v0.2.xlsx"
local sheet "Merged sample"

*------------------------------------------------------------------------------
* 1. Column map: new names, in sheet order, matched to the expected headers
*------------------------------------------------------------------------------
local vars                                                                   ///
    journal year title doi abstract                                          ///
    pol_cites pol_cited_any pol_cites_all pol_cites_excl_wp                  ///
    pol_cites_gov pol_cites_igo pol_cites_leg pol_cites_thinktank            ///
    pol_cites_us pol_cites_europe pol_cites_intl pol_cites_othctry           ///
    pol_n_citing_orgs pol_first_year pol_years_to_first                      ///
    acad_cites fwci n_refs n_authors n_insts n_countries                     ///
    author_names author_insts author_countries journal_name                  ///
    pub_date_str volume issue pages                                          ///
    oa_topic oa_subfield oa_keywords open_access oa_status                   ///
    top15_econ top15_all                                                     ///
    item_type topic_llm jel_model jel_authors research_type emp_design       ///
    pc_novel_policy pc_causal_effect pc_descriptive pc_unintended            ///
    pc_predicts_model pc_cost_benefit pc_mechanisms pc_specific_groups       ///
    primary_pc policy_studied policy_eval                                    ///
    jargon sent_complexity flesch_ease fk_grade                              ///
    author_disciplines multidisc multidisc_noneb llm_notes openalex_id

* Expected header for each column, in sheet order (h1..h67)
local h1  "Journal"                                       // journal
local h2  "Year"                                          // year
local h3  "Title"                                         // title
local h4  "DOI"                                           // doi
local h5  "Abstract"                                      // abstract
local h6  "Policy citations"                              // pol_cites
local h7  "Cited in policy (any)"                         // pol_cited_any
local h8  "All Overton citations (incl. excluded)"        // pol_cites_all
local h9  "Excluded (academic working papers)"            // pol_cites_excl_wp
local h10 "Citations: government"                         // pol_cites_gov
local h11 "Citations: IGO"                                // pol_cites_igo
local h12 "Citations: legislature"                        // pol_cites_leg
local h13 "Citations: think tank / NGO"                   // pol_cites_thinktank
local h14 "Citations: US"                                 // pol_cites_us
local h15 "Citations: Europe"                             // pol_cites_europe
local h16 "Citations: international bodies"               // pol_cites_intl
local h17 "Citations: other countries"                    // pol_cites_othctry
local h18 "Distinct citing organisations"                 // pol_n_citing_orgs
local h19 "First policy citation (year)"                  // pol_first_year
local h20 "Years to first policy citation"                // pol_years_to_first
local h21 "Academic citations (OpenAlex)"                 // acad_cites
local h22 "Field-weighted citation impact"                // fwci
local h23 "References"                                    // n_refs
local h24 "Authors (n)"                                   // n_authors
local h25 "Institutions (n)"                              // n_insts
local h26 "Countries (n)"                                 // n_countries
local h27 "Author names"                                  // author_names
local h28 "Author institutions"                           // author_insts
local h29 "Author countries"                              // author_countries
local h30 "Journal (full name)"                           // journal_name
local h31 "Publication date"                              // pub_date_str
local h32 "Volume"                                        // volume
local h33 "Issue"                                         // issue
local h34 "Pages"                                         // pages
local h35 "OpenAlex topic"                                // oa_topic
local h36 "OpenAlex subfield"                             // oa_subfield
local h37 "OpenAlex keywords"                             // oa_keywords
local h38 "Open access"                                   // open_access
local h39 "Open access status"                            // oa_status
local h40 "In top-15 economics journals"                  // top15_econ
local h41 "In top-15 (all fields)"                        // top15_all
local h42 "Item type"                                     // item_type
local h43 "Topic"                                         // topic_llm
local h44 "JEL codes (model)"                             // jel_model
local h45 "JEL codes (authors, if listed)"                // jel_authors
local h46 "Research type"                                 // research_type
local h47 "Empirical design"                              // emp_design
local h48 "Proposes novel policy"                         // pc_novel_policy
local h49 "Causal effect of policy"                       // pc_causal_effect
local h50 "Descriptive fact"                              // pc_descriptive
local h51 "Unintended consequences"                       // pc_unintended
local h52 "Predicts effects with models"                  // pc_predicts_model
local h53 "Cost benefit or welfare"                       // pc_cost_benefit
local h54 "Identifies mechanisms"                         // pc_mechanisms
local h55 "Impacts on specific groups"                    // pc_specific_groups
local h56 "Primary policy category"                       // primary_pc
local h57 "Policy studied"                                // policy_studied
local h58 "Policy evaluation"                             // policy_eval
local h59 "Jargon (1-5)"                                  // jargon
local h60 "Sentence complexity (1-5)"                     // sent_complexity
local h61 "Flesch reading ease"                           // flesch_ease
local h62 "Flesch-Kincaid grade"                          // fk_grade
local h63 "Author disciplines"                            // author_disciplines
local h64 "Multidisciplinary team"                        // multidisc
local h65 "Multidisciplinary beyond econ/business"        // multidisc_noneb
local h66 "Model notes"                                   // llm_notes
local h67 "OpenAlex ID"                                   // openalex_id

local K : word count `vars'
assert `K' == 67

*------------------------------------------------------------------------------
* 2. Check the header row matches the map (fails if columns move or change)
*------------------------------------------------------------------------------
import excel using "`xlsx'", sheet("`sheet'") cellrange(A1:BO1) allstring clear
unab cols : _all
assert `: word count `cols'' == `K'
forvalues i = 1/`K' {
    local c : word `i' of `cols'
    local h "`h`i''"
    if strtrim(`c'[1]) != `"`h'"' {
        di as error `"Column `c': expected "`h'", found "`=`c'[1]'""'
        exit 9
    }
}

*------------------------------------------------------------------------------
* 3. Import the data, rename, label with the original headers
*------------------------------------------------------------------------------
import excel using "`xlsx'", sheet("`sheet'") cellrange(A2) clear
unab cols : _all
assert `: word count `cols'' == `K'
rename (`cols') (`vars')

forvalues i = 1/`K' {
    local v : word `i' of `vars'
    local h "`h`i''"
    label variable `v' `"`h'"'
}

drop if missing(doi) & missing(title)     // stray blank rows, if any

* Issue mixes numbers and text ("4-5", "S1") - keep as string
capture confirm string variable issue
if _rc tostring issue, replace

*------------------------------------------------------------------------------
* 4. Tidy strings
*------------------------------------------------------------------------------
ds, has(type string)
foreach v in `r(varlist)' {
    replace `v' = strtrim(stritrim(`v'))
}
replace doi = lower(doi)

*------------------------------------------------------------------------------
* 5. Yes/No -> 0/1 (blank -> missing)
*------------------------------------------------------------------------------
label define yesno 0 "No" 1 "Yes"

local yesno pol_cited_any open_access top15_econ top15_all                   ///
    pc_novel_policy pc_causal_effect pc_descriptive pc_unintended            ///
    pc_predicts_model pc_cost_benefit pc_mechanisms pc_specific_groups       ///
    policy_eval multidisc multidisc_noneb

foreach v of local yesno {
    assert inlist(`v', "Yes", "No", "")
    local lab : variable label `v'
    gen byte `v'_n = cond(`v' == "Yes", 1, cond(`v' == "No", 0, .))
    order `v'_n, after(`v')
    drop `v'
    rename `v'_n `v'
    label variable `v' `"`lab'"'
    label values `v' yesno
}

*------------------------------------------------------------------------------
* 6. Categorical codes -> labelled numerics
*    noextend: errors if a value appears that is not in the codebook
*------------------------------------------------------------------------------
label define research_type 1 "empirical" 2 "theory_and_empirical"            ///
    3 "theoretical" 4 "econometric_methods" 5 "review_or_synthesis" 6 "other"
label define emp_design 1 "experimental" 2 "quasi_experimental"              ///
    3 "structural" 4 "descriptive_or_correlational"                          ///
    5 "forecasting_or_calibration" 6 "not_empirical"
* "proposes_novel_policy" does not occur in v0.2 - spelling assumed
label define primary_pc 0 "none" 1 "proposes_novel_policy"                  ///
    2 "causal_effect_of_policy" 3 "descriptive_fact"                         ///
    4 "unintended_consequences" 5 "predicts_effects_with_models"             ///
    6 "cost_benefit_or_welfare" 7 "identifies_mechanisms"                    ///
    8 "impacts_on_specific_groups"
label define policy_studied 0 "none" 1 "existing_policy"                     ///
    2 "proposed_or_hypothetical_policy" 3 "both"
label define item_type 1 "research_article" 2 "review_article" 3 "non_research"
label define oa_status 1 "gold" 2 "diamond" 3 "hybrid" 4 "bronze"            ///
    5 "green" 6 "closed"

foreach v in research_type emp_design primary_pc policy_studied item_type oa_status {
    local lab : variable label `v'
    encode `v', gen(`v'_n) label(`v') noextend
    order `v'_n, after(`v')
    drop `v'
    rename `v'_n `v'
    label variable `v' `"`lab'"'
}

* Journal: keep the short code (string) and add a labelled numeric version
encode journal, gen(journal_id)
order journal_id, after(journal)
label variable journal_id "Journal (numeric)"

*------------------------------------------------------------------------------
* 7. Dates and IDs
*------------------------------------------------------------------------------
gen pub_date = date(pub_date_str, "YMD")
format pub_date %td
assert !missing(pub_date) if pub_date_str != ""
assert year(pub_date) == year
order pub_date, after(pub_date_str)
drop pub_date_str
label variable pub_date "Publication date"

gen openalex_wid = subinstr(openalex_id, "https://openalex.org/", "", 1)
order openalex_wid, after(openalex_id)
label variable openalex_wid "OpenAlex work ID (W...)"

isid doi
isid openalex_id

*------------------------------------------------------------------------------
* 8. Range and consistency checks (all hold in v0.2)
*------------------------------------------------------------------------------
assert inrange(jargon, 1, 5)
assert inrange(sent_complexity, 1, 5)
assert inrange(year, 2016, 2025)

assert pol_cited_any == (pol_cites > 0)
assert pol_cites_all == pol_cites + pol_cites_excl_wp
assert pol_cites == pol_cites_gov + pol_cites_igo + pol_cites_leg + pol_cites_thinktank
assert pol_cites == pol_cites_us + pol_cites_europe + pol_cites_intl + pol_cites_othctry
assert missing(pol_first_year) == (pol_cites == 0)
assert pol_years_to_first == pol_first_year - year if !missing(pol_first_year)

* Policy evaluation is computed from other codes (see Read me sheet)
assert policy_eval == ((pc_causal_effect | pc_unintended)                    ///
    & inlist(emp_design, 1, 2, 3))

* Some papers are cited in policy before journal publication (working-paper
* versions), so years-to-first can be negative. Flag rather than drop.
gen byte pol_cited_prepub = pol_years_to_first < 0 if !missing(pol_years_to_first)
label values pol_cited_prepub yesno
label variable pol_cited_prepub "First policy citation before publication year"
order pol_cited_prepub, after(pol_years_to_first)

*------------------------------------------------------------------------------
* 9. Save
*------------------------------------------------------------------------------
compress
label data "Overton merged sample v0.2: 100 papers, one row per paper"
note: Source: `xlsx', sheet "`sheet'". Created by analysis/01_import_clean.do on `c(current_date)'.
sort journal year doi

describe, short
codebook pol_cites acad_cites research_type emp_design primary_pc, compact

save "analysis/output/overton_sample_clean.dta", replace

log close
