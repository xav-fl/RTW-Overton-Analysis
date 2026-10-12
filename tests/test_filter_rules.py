import pandas as pd
import pytest

from overton import filter_rules as fr
from overton.filter import apply_filter


def rec(title="A Study of Things", **kw):
    base = {"title": title, "openalex_type": "article", "is_paratext": False,
            "is_retracted": False, "has_abstract": True, "doi": "10.1/x", "n_authors": 2,
            "page_count": 30, "journal_key": "aer", "publication_year": 2016,
            "volume": "106", "language": "en"}
    base.update(kw)
    return base


def reason(title, **kw):
    return fr.exclusion_reason(rec(title, **kw))


def flags(title="A Study of Things", **kw):
    r = rec(title, **kw)
    return fr.review_flags(r, excluded=bool(fr.exclusion_reason(r)))


# -- one positive and one negative per exclusion rule -------------------------

@pytest.mark.parametrize("code,positive,negative", [
    ("E_CORRECTION", "Corrigendum: Trade and Growth", "Correction of Measurement Error in Survey Income"),
    ("E_CORRECTION", "Correction to “Trade and Growth”", "Corrective Taxes and Externalities"),
    ("E_CORRECTION", "Retraction", "Retractions and Scientific Credibility"),
    ("E_COMMENT", "Comment on “Minimum Wages and Employment”", "Commenting Behaviour Online"),
    ("E_COMMENT", "Minimum Wages and Employment: Comment", "No Comment Needed: Disclosure Rules"),
    ("E_COMMENT", "Minimum Wages and Employment — Reply", "Reply Rates in Online Dating Markets"),
    ("E_COMMENT", "Rejoinder", "Rejoinders in Political Debate"),
    ("E_FRONTMATTER", "Front Matter", "Front-Running in Bond Markets"),
    ("E_FRONTMATTER", "Index", "Index Insurance and Farmer Welfare"),
    ("E_FRONTMATTER", "Cover", "Cover Crops and Farm Profits"),
    ("E_FRONTMATTER", "Issue Information", "Information Frictions in Issue Markets"),
    ("E_ADMIN", "Report of the Editor: American Economic Review", "Annual Report Readability and Investment Efficiency"),
    ("E_ADMIN", "Announcements", "Announcement Effects of Monetary Policy"),
    ("E_ADMIN", "Election of Fellows to the Econometric Society", "Election of Women and Local Public Spending"),
    ("E_ADMIN", "Editor’s Note", "Editors and the Allocation of Attention"),
    ("E_ADMIN", "Editorial", "Editorial Boards and Publication Bias"),
    ("E_ADMIN", "In Memoriam: John Doe", "Memory and Expectations"),
    ("E_BOOKS", "Book Reviews", "Booking Profits: Hotels and Taxes"),
    ("E_BOOKS", "Annotated Listing of New Books", "New Bookstores and Local Reading"),
    ("E_READING", "Recommendations for Further Reading", "Reading Skills and Wages"),
    ("E_READING", "Correspondence", "Correspondence Bias in Hiring Experiments"),
])
def test_title_rule(code, positive, negative):
    assert reason(positive) == code
    assert reason(negative) == ""


def test_e_type():
    assert reason("Some Paper", openalex_type="erratum") == "E_TYPE:erratum"
    assert reason("Some Paper", openalex_type=None) == "E_TYPE:none"
    assert reason("Some Paper", openalex_type="review") == ""
    assert reason("Some Paper", openalex_type="article") == ""


def test_e_paratext():
    assert reason("Some Paper", is_paratext=True) == "E_PARATEXT"
    assert reason("Some Paper", is_paratext="True") == "E_PARATEXT"
    assert reason("Some Paper", is_paratext=False) == ""


def test_first_matching_rule_wins():
    assert reason("Erratum", openalex_type="erratum") == "E_TYPE:erratum"
    assert reason("Comment on the Erratum") == "E_CORRECTION"


@pytest.mark.parametrize("title", [
    "Index Insurance and Farmer Welfare",
    "Announcement Effects of Monetary Policy",
    "Annual Report Readability and Investment Efficiency",
    "Election of Women and Local Public Spending",
    "Response to Monetary Policy Shocks across Firms",
    "Correction of Measurement Error in Survey Income",
    "Cover Crops and Farm Profits",
    "Editorial Boards and Publication Bias",
])
def test_brief_negative_cases_never_excluded(title):
    assert reason(title) == ""


def test_colon_alternatives_and_trailing_punctuation():
    assert reason("Trade and Growth – Comment") == "E_COMMENT"
    assert reason("Trade and Growth - Reply.") == "E_COMMENT"
    assert reason("Correction — Trade and Growth") == "E_CORRECTION"
    assert reason("  Front matter.  ") == "E_FRONTMATTER"
    assert reason("Trade-Comment Linkages") == ""


# -- one positive and one negative per review flag ----------------------------

@pytest.mark.parametrize("code,pos_kw,neg_kw", [
    ("F_SHORT", {"page_count": 3}, {"page_count": 4}),
    ("F_NO_AUTHORS", {"n_authors": 0}, {"n_authors": 1}),
    ("F_NO_ABSTRACT_NO_DOI", {"has_abstract": False, "doi": ""}, {"has_abstract": False}),
    ("F_RETRACTED", {"is_retracted": True}, {"is_retracted": False}),
    ("F_JEL_NO_ABSTRACT", {"journal_key": "jel", "has_abstract": False},
     {"journal_key": "jel", "has_abstract": True}),
])
def test_field_flags(code, pos_kw, neg_kw):
    assert code in flags(**pos_kw)
    assert code not in flags(**neg_kw)


def test_short_flag_ignores_missing_page_count():
    assert "F_SHORT" not in flags(page_count=None)


@pytest.mark.parametrize("code,positive,negative", [
    ("F_COMMENT_WORD", "Response to Monetary Policy Shocks across Firms", "Monetary Policy Shocks"),
    ("F_COMMENT_WORD", "Public Comments and Regulation", "Commerce and Regulation"),
    ("F_ADMIN_WORD", "Index Insurance and Farmer Welfare", "Indexation of Pensions"),
    ("F_ADMIN_WORD", "Editorial Boards and Publication Bias", "Editors and Bias"),
    ("F_INTRO", "Introduction to the Symposium on Inequality", "An Introduction of New Goods"),
    ("F_INTRO", "Symposium: Inequality", "Inequality Symposium"),
    ("F_INTRO", "Foreword", "A Word Before"),
])
def test_title_flags(code, positive, negative):
    assert code in flags(positive)
    assert code not in flags(negative)


def test_word_flags_only_when_not_excluded():
    assert "F_COMMENT_WORD" not in flags("Comment on Trade")       # excluded by E_COMMENT
    assert "F_ADMIN_WORD" not in flags("Editorial")                # excluded by E_ADMIN


def test_fingerprint_stable_and_versioned():
    assert fr.FILTER_VERSION == "F2"
    assert fr.rules_fingerprint() == fr.rules_fingerprint()
    assert len(fr.rules_fingerprint()) == 12


def test_apply_filter_columns():
    df = pd.DataFrame([rec("Front Matter"), rec("Index Insurance and Farmer Welfare")])
    out = apply_filter(df)
    assert list(out["include"]) == [False, True]
    assert list(out["exclusion_reason"]) == ["E_FRONTMATTER", ""]
    assert out.loc[1, "review_flags"] == "F_ADMIN_WORD"
    assert set(out["filter_version"]) == {"F2"}
    assert set(out["rules_fingerprint"]) == {fr.rules_fingerprint()}


# -- F2 rules -----------------------------------------------------------------

def test_e_misdated():
    floor = {"doi_volume_floor": 106.0}
    assert reason("Bargaining under Uncertainty", doi="", volume="79", **floor) == "E_MISDATED"
    assert reason("Bargaining under Uncertainty", doi="10.1/x", volume="79", **floor) == ""
    assert reason("A 2016 Paper", doi="", volume="106", **floor) == ""
    assert reason("A 2016 Paper", doi="", volume="105", **floor) == ""      # within slack
    assert reason("A 2016 Paper", doi="", volume="", **floor) == ""
    assert reason("A 2016 Paper", doi="", volume="79", doi_volume_floor=None) == ""


def test_e_nonenglish_no_doi():
    assert reason("鋼の極微細世界", doi="", language="ja") == "E_NONENGLISH_NO_DOI"
    assert reason("Un article", doi="10.1/x", language="fr") == ""
    assert reason("A Paper", doi="", language="en") == ""
    assert reason("A Paper", doi="", language="") == ""


def test_f1_rules_take_precedence_over_f2():
    assert reason("Comment", doi="", volume="70", doi_volume_floor=106.0) == "E_COMMENT"


def test_apply_filter_computes_volume_floor_per_journal_year():
    df = pd.DataFrame([
        rec("New Paper A", doi="10.1/a", volume="106"),
        rec("New Paper B", doi="10.1/b", volume="107"),
        rec("Old Paper", doi="", volume="72"),
        rec("Undated Item", doi="", volume=""),
        rec("Other Journal Old", doi="", volume="72", journal_key="qje"),   # no DOI floor
    ])
    out = apply_filter(df)
    assert list(out["exclusion_reason"]) == ["", "", "E_MISDATED", "", ""]
