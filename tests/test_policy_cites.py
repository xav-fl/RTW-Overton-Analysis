import pandas as pd
import pytest

from overton import policy_cites
from overton.settings import Paths


def doc(i, cited, org="Government", dtype="Publication", title=None, country="USA",
        date="2021/05/01", source="src"):
    return {"Overton document ID": f"d{i}", "Document title": title or f"Doc {i}",
            "Document type": dtype, "Document series": None, "Cited DOIs": cited,
            "Publication date": date, "Overton source ID": source, "Source name": source,
            "Source organisation type": org, "Source country": country, "Overton URL": ""}


def test_doc_rule():
    assert policy_cites.doc_rule("Government", "Working paper") == (True, "public source")
    assert policy_cites.doc_rule("IGO", "Working paper")[0] is True
    assert policy_cites.doc_rule("Think Tank", "Working paper")[0] is False
    assert policy_cites.doc_rule("NGO", "Working paper")[0] is False
    assert policy_cites.doc_rule("Think Tank", "Publication")[0] is True
    assert policy_cites.doc_rule("Government", "Scholarly article")[0] is False


def test_region():
    assert [policy_cites.region(c) for c in ("USA", "IGO", "Germany", "EU", "Japan")] == \
        ["us", "international", "europe", "europe", "other"]


@pytest.fixture
def project(tmp_path):
    paths = Paths(tmp_path)
    paths.overton_queried.mkdir(parents=True)
    (paths.overton_queried / "batch.txt").write_text("10.1/a\nhttps://doi.org/10.1/B\n10.1/c\n",
                                                     encoding="utf-8")
    pd.DataFrame([
        doc(1, "10.1/a ; 10.9/other"),                                   # counts
        doc(2, "10.1/A", org="Think Tank", dtype="Working paper", source="nber"),  # excluded
        doc(3, "10.1/a", org="Think Tank", dtype="Publication", country="Germany"),
        doc(4, "10.1/a", title="Doc 1", date="2023/01/01"),             # duplicate of doc 1
        doc(5, "10.1/b", org="IGO", dtype="Working paper", country="IGO", date="2019/01/01"),
        doc(6, "10.1/zz"),                                               # cites nothing of ours
        doc(7, "10.1/b", title="성별 임금격차"),                         # Korean titles differ
        doc(8, "10.1/b", title="지역 경제"),
    ]).to_csv(paths.overton_raw / "export.csv", index=False)
    return paths


def test_merge_counts(project):
    coded = pd.DataFrame({"doi": ["10.1/a", "10.1/b", "10.1/c", "10.1/d"],
                          "publication_year": [2018, 2016, 2020, 2020]})
    out, links, sources = policy_cites.merge(project, coded)
    out = out.set_index("doi")
    a, b, c, d = (out.loc[x] for x in ("10.1/a", "10.1/b", "10.1/c", "10.1/d"))
    assert a["policy_cites"] == 2 and a["policy_cites_all"] == 3          # docs 1, 3; +nber
    assert a["policy_cites_excluded"] == 1
    assert a["policy_cites_government"] == 1 and a["policy_cites_think_tank_ngo"] == 1
    assert a["policy_cites_us"] == 1 and a["policy_cites_europe"] == 1
    assert a["policy_first_cite_year"] == 2021 and a["policy_years_to_first_cite"] == 3
    assert b["policy_cites"] == 3 and b["policy_cites_igo"] == 1           # IGO working paper kept
    assert b["policy_cites_international"] == 1
    assert c["policy_cites"] == 0 and c["policy_cited_any"] == False      # noqa: E712 - searched
    assert d["overton_queried"] == False and pd.isna(d["policy_cites"])   # noqa: E712 - not searched
    assert int(links["duplicate"].sum()) == 1
    nber = sources.set_index("source_id").loc["nber"]
    assert nber["excluded"] == 1 and nber["counted"] == 0
    assert project.papers_cited.exists() and project.overton_sources.exists()


def test_missing_inputs_are_errors(tmp_path):
    paths = Paths(tmp_path)
    with pytest.raises(FileNotFoundError):
        policy_cites.load_exports(paths)
    with pytest.raises(FileNotFoundError):
        policy_cites.queried_dois(paths)
