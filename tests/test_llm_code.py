import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from overton import features, llm_assemble, llm_code
from overton.settings import ROOT, Paths

ABSTRACT = ("We exploit the staggered introduction of a minimum wage increase across states "
            "to estimate its effect on teen employment. Employment falls slightly, and the "
            "losses are concentrated among workers in small firms. We also find that hours "
            "rise for those who keep their jobs. (JEL J23, J31, J38)")


# -- features -----------------------------------------------------------------

def test_author_jel_codes_variants():
    assert features.author_jel_codes(ABSTRACT) == ["J23", "J31", "J38"]
    assert features.author_jel_codes("Text. JEL Classification: D82; G21.") == ["D82", "G21"]
    assert features.author_jel_codes("Text. (JEL, E23, E31)") == ["E23", "E31"]
    assert features.author_jel_codes("Published in JEL, JEL on CD, and EconLit.") == []


def test_clean_abstract_removes_jel_list():
    clean = features.clean_abstract(ABSTRACT)
    assert "JEL" not in clean
    assert clean.endswith("keep their jobs.")


def test_readability_is_plausible():
    r = features.readability("The cat sat. The dog ran far away.")
    assert r["abs_n_sentences"] == 2
    assert r["abs_words_per_sentence"] == 4.0
    assert r["abs_flesch_reading_ease"] > 90
    assert features.readability("")["abs_n_sentences"] is None


def test_discipline_summary():
    s = features.discipline_summary(["economics", "economics"])
    assert s["multidisciplinary"] is False
    s = features.discipline_summary(["economics", "finance_accounting"])
    assert s["multidisciplinary"] is True
    assert s["multidisciplinary_beyond_econ_business"] is False
    s = features.discipline_summary(["economics", "medicine_public_health", "unknown"])
    assert s["multidisciplinary_beyond_econ_business"] is True
    assert s["share_authors_unknown_discipline"] == pytest.approx(0.333)
    assert features.discipline_summary(["unknown"])["multidisciplinary"] is None


# -- prompt and request -------------------------------------------------------

def test_run_key_changes_with_model_effort_and_prompt():
    k = llm_code.run_key("sys", "m", "medium")
    assert k == llm_code.run_key("sys", "m", "medium")
    assert k != llm_code.run_key("sys", "m", "low")
    assert k != llm_code.run_key("sys2", "m", "medium")


def test_schema_objects_are_closed():
    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for v in node.values():
                walk(v)
    walk(llm_code.schema())


def test_user_message_with_and_without_abstract():
    paper = {"title": "T", "source_display_name": "AER", "publication_year": 2020,
             "abstract_clean": "An abstract."}
    authors = [{"affiliation": "Dept of Economics, MIT", "institutions": "MIT"}]
    m = llm_code.user_message(paper, authors, True)
    assert "ABSTRACT: An abstract." in m and "1. affiliation: Dept of Economics" in m
    assert "ABSTRACT: none" in llm_code.user_message(paper, authors, False)
    assert "AUTHORS: none listed" in llm_code.user_message(paper, [], True)


def test_system_prompt_contains_codebook_and_taxonomy():
    s = llm_code.system_prompt(Paths())
    assert "PAPER CODEBOOK" in s and "J31 |" in s


# -- validation ---------------------------------------------------------------

def good_answer(n_authors=2, **over):
    a = {
        "item_type": "research_article", "topic_label": "Minimum wage and teen jobs",
        "jel_codes": ["J31", "j23"], "research_type": "empirical",
        "empirical_design": "quasi_experimental",
        "policy_categories": {c: False for c in llm_code.POLICY_CATEGORIES},
        "primary_policy_category": "causal_effect_of_policy",
        "policy_reference": "existing_policy", "jargon": 2, "sentence_complexity": 2,
        "author_disciplines": [{"author": i, "discipline": "economics"}
                               for i in range(1, n_authors + 1)],
        "notes": "",
    }
    a["policy_categories"]["causal_effect_of_policy"] = True
    a["policy_categories"]["impacts_on_specific_groups"] = True
    a.update(over)
    return a


def test_validate_clean_answer():
    out, problems = llm_code.validate(good_answer(), 2, {"J31", "J23"})
    assert problems == []
    assert out["jel_codes"] == ["J31", "J23"]
    assert out["author_disciplines"] == ["economics", "economics"]


def test_validate_flags_problems():
    ans = good_answer(jel_codes=["J31", "Z99", "J23", "J38", "J24"],
                      primary_policy_category="descriptive_fact",
                      author_disciplines=[{"author": 1, "discipline": "law"}])
    out, problems = llm_code.validate(ans, 2, {"J31", "J23", "J38", "J24"})
    assert out["jel_codes"] == ["J31", "J23", "J38"]
    assert out["author_disciplines"] == ["law", "unknown"]
    text = " ".join(problems)
    assert "Z99" in text and "kept the first 3" in text
    assert "descriptive_fact not marked yes" in text and "author_disciplines" in text


def test_cost():
    u = {"input_tokens": 1_000_000, "output_tokens": 0, "cache_creation_input_tokens": 0,
         "cache_read_input_tokens": 0}
    assert llm_code.cost_usd(u, "claude-opus-5-5", batch=False) == pytest.approx(4.0)
    assert llm_code.cost_usd(u, "claude-opus-5-5", batch=True) == pytest.approx(2.0)
    assert llm_code.cost_usd(u, "unknown-model", batch=False) is None


# -- end to end with a fake client --------------------------------------------

class FakeMessages:
    def __init__(self, answer_for):
        self.answer_for = answer_for
        self.calls = []

    def create(self, betas=None, **params):
        self.calls.append((betas, params))
        user = params["messages"][0]["content"]
        n = sum(1 for line in user.splitlines() if line[:1].isdigit() and ". affiliation:" in line)
        text, stop = self.answer_for(user, n)
        return SimpleNamespace(
            model=params["model"], stop_reason=stop, stop_details=None,
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=500, output_tokens=300,
                                  cache_creation_input_tokens=0,
                                  cache_read_input_tokens=12000))


@pytest.fixture
def project(tmp_path):
    """A tmp project with the real config and three Stage 1 papers."""
    shutil.copytree(ROOT / "config", tmp_path / "config")
    rel = tmp_path / "data" / "release"
    rel.mkdir(parents=True)
    papers = pd.DataFrame([
        {"openalex_id": "https://openalex.org/W1", "doi": "10.1/a", "title": "Minimum wages",
         "publication_year": 2020, "journal_key": "aer", "source_display_name": "AER",
         "abstract": ABSTRACT},
        {"openalex_id": "https://openalex.org/W2", "doi": "10.1/b", "title": "A theory",
         "publication_year": 2021, "journal_key": "ecta", "source_display_name": "Econometrica",
         "abstract": ""},
        {"openalex_id": "https://openalex.org/W3", "doi": "10.1/c", "title": "Broken",
         "publication_year": 2022, "journal_key": "aer", "source_display_name": "AER",
         "abstract": ABSTRACT},
    ])
    papers.to_csv(rel / "papers_stage1.csv", index=False)
    auth = pd.DataFrame([
        {"openalex_id": "https://openalex.org/W1", "author_order": 1, "author_id": "A1",
         "institution_name": "MIT", "raw_affiliation_strings": "Department of Economics, MIT"},
        {"openalex_id": "https://openalex.org/W1", "author_order": 2, "author_id": "A2",
         "institution_name": "Harvard", "raw_affiliation_strings": "School of Public Health"},
        {"openalex_id": "https://openalex.org/W2", "author_order": 1, "author_id": "A3",
         "institution_name": "LSE", "raw_affiliation_strings": "LSE"},
        {"openalex_id": "https://openalex.org/W3", "author_order": 1, "author_id": "A4",
         "institution_name": "UCL", "raw_affiliation_strings": "UCL"},
    ])
    auth.to_csv(rel / "authorships_stage1.csv", index=False)
    return Paths(tmp_path)


def fake_answers(user, n):
    if "TITLE: Broken" in user:
        return "not json", "end_turn"
    discs = ["economics", "medicine_public_health"][:n] if "Minimum" in user else ["unknown"]
    ans = good_answer(n_authors=n, author_disciplines=[
        {"author": i + 1, "discipline": d} for i, d in enumerate(discs)])
    return json.dumps(ans), "end_turn"


def test_run_resume_and_assemble(project):
    df = llm_code.load_inputs(project)
    client = SimpleNamespace(beta=SimpleNamespace(messages=FakeMessages(fake_answers)))
    send = llm_code.api_sender(client, llm_code.system_prompt(project))
    recs = llm_code.run_sync(project, send, df, model="claude-opus-5-5", effort="medium",
                             workers=2, log=lambda *_: None)
    assert sorted(r["status"] for r in recs) == ["ok", "ok", "parse_error"]
    betas, params = client.beta.messages.calls[0]
    assert betas == [llm_code.FALLBACK_BETA] and params["fallbacks"] == "default"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "JEL" not in params["messages"][0]["content"].split("ABSTRACT:")[1].split("AUTHORS")[0]

    key = llm_code.run_key(llm_code.system_prompt(project), "claude-opus-5-5", "medium")
    done = llm_code.Store(project).done(key)
    assert done == {"W1", "W2"}
    assert list(llm_code.select(df, done, None, None)["custom_id"]) == ["W3"]

    out = llm_assemble.assemble(project, key).set_index("openalex_id")
    w1 = out.loc["https://openalex.org/W1"]
    assert w1["llm_coded_from"] == "abstract"
    assert w1["jel_codes_author"] == "J23; J31; J38"
    assert w1["llm_jel_overlaps_author"] == True  # noqa: E712
    assert w1["multidisciplinary_beyond_econ_business"] == True  # noqa: E712
    assert w1["llm_causal_design"] == True  # noqa: E712
    w2 = out.loc["https://openalex.org/W2"]
    assert w2["llm_coded_from"] == "title_only"
    assert pd.isna(w2["llm_research_type"]) and w2["llm_jel_primary"] == "J31"
    assert out.loc["https://openalex.org/W3"]["llm_coded_from"] == "not_coded"
    discs = pd.read_csv(project.author_disciplines).sort_values(["openalex_id", "author_order"])
    assert list(discs["discipline"]) == ["economics", "medicine_public_health", "unknown"]

    llm_assemble.report(project, out.reset_index(), key)
    assert "coded from abstract: 1" in project.llm_report.read_text(encoding="utf-8")


def test_provider_stop_halts_run(project):
    class Billing(Exception):
        status_code = 400

        def __str__(self):
            return "Your credit balance is too low"

    class Broke:
        def create(self, **_):
            raise Billing()

    df = llm_code.load_inputs(project)
    client = SimpleNamespace(beta=SimpleNamespace(messages=Broke()))
    with pytest.raises(llm_code.ProviderStopped, match="out of credit"):
        llm_code.run_sync(project, llm_code.api_sender(client, "sys"), df, model="m",
                          effort="low", log=lambda *_: None)
    assert llm_code.Store(project).records() == []


def test_refusal_and_max_tokens_are_recorded():
    msg = SimpleNamespace(model="m", stop_reason="refusal",
                          stop_details=SimpleNamespace(category="cyber"), content=[], usage=None)
    r = llm_code.record_from_message(msg, "W1", "k", "m", "low", "sync")
    assert r["status"] == "refusal" and r["error"] == "cyber"
    msg = SimpleNamespace(model="m", stop_reason="max_tokens", content=[], usage=None)
    assert llm_code.record_from_message(msg, "W1", "k", "m", "low", "sync")["status"] == "max_tokens"


def test_agreement_and_kappa(project, tmp_path):
    coded = pd.DataFrame({"openalex_id": ["a", "b", "c", "d"],
                          "llm_item_type": ["research_article"] * 4,
                          "llm_jargon": [2, 3, 4, 5], "multidisciplinary": [True, False, False, True]})
    for col in llm_assemble.HUMAN_FIELDS.values():
        if col not in coded:
            coded[col] = None
    human = pd.DataFrame({"openalex_id": ["a", "b", "c", "d"],
                          **{c: "" for c in llm_assemble.HUMAN_FIELDS}})
    human["human_item_type"] = "research_article"
    human["human_jargon"] = ["2", "3", "2", "5"]
    human["human_multidisciplinary"] = ["yes", "no", "yes", "yes"]
    f = tmp_path / "human.csv"
    human.to_csv(f, index=False)
    out = llm_assemble.agreement(project, f, coded).set_index("field")
    assert out.loc["jargon", "agreement"] == 0.75
    assert out.loc["jargon", "within_one"] == 0.75
    assert out.loc["multidisciplinary", "agreement"] == 0.75
    assert out.loc["research_type", "n"] == 0
    assert llm_assemble.cohen_kappa(["1", "0", "1", "0"], ["1", "0", "1", "0"]) == 1.0
