import gzip
import json
from pathlib import Path

import pytest

from overton import harvest
from overton.normalise import (AUTHORSHIP_COLUMNS, WORK_COLUMNS, authorship_rows,
                               normalise, normalise_doi, page_count,
                               reconstruct_abstract, work_row)
from overton.settings import Paths

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_b() -> dict:
    return json.loads((FIXTURES / "b_works_aer_2020_primary.json").read_text(encoding="utf-8"))


# -- abstract reconstruction --------------------------------------------------

def test_abstract_null_and_empty():
    assert reconstruct_abstract(None) == ""
    assert reconstruct_abstract({}) == ""


def test_abstract_orders_by_position():
    assert reconstruct_abstract({"world": [1], "hello": [0]}) == "hello world"


def test_abstract_repeated_words_at_several_positions():
    idx = {"the": [0, 4], "cat": [1], "saw": [2, 6], "a": [3], "dog": [5], "it": [7]}
    assert reconstruct_abstract(idx) == "the cat saw a the dog saw it"


def test_abstract_strips_and_handles_empty_position_list():
    assert reconstruct_abstract({"x": [0], "y": []}) == "x"


# -- DOI ---------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("https://doi.org/10.1257/AER.123", "10.1257/aer.123"),
    ("http://dx.doi.org/10.1093/QJE/QJZ001", "10.1093/qje/qjz001"),
    ("10.1257/ABC", "10.1257/abc"),
    (None, None),
    ("", None),
])
def test_doi_normalisation(raw, expected):
    assert normalise_doi(raw) == expected


def test_page_count():
    assert page_count("2964", "2996") == 33
    assert page_count("1", "1") == 1
    assert page_count("e12", "e20") is None
    assert page_count(None, "5") is None


# -- fixture (b) -> Appendix A ------------------------------------------------

def test_fixture_b_work_rows():
    data = fixture_b()
    rows = [work_row(w, "aer", "2026-10-12", "raw.json.gz") for w in data["response"]["results"]]
    assert len(rows) == 5
    for r in rows:
        assert list(r) == WORK_COLUMNS
        assert r["journal_key"] == "aer"
        assert r["source_id"] == "https://openalex.org/S23254222"
        assert r["publication_year"] == 2020
        assert r["doi"].startswith("10.1257/aer.") and r["doi"] == r["doi"].lower()
        assert r["openalex_type"] == "article"
        assert r["has_abstract"] and r["abstract_word_count"] > 20
        assert r["n_authors"] >= 1
        assert isinstance(r["page_count"], int) and r["page_count"] > 3
        assert r["harvest_date"] == "2026-10-12"
    first = rows[0]
    assert first["title"].startswith("Two-Way Fixed Effects")
    assert first["page_count"] == 2996 - 2964 + 1


def test_fixture_b_authorship_rows():
    for w in fixture_b()["response"]["results"]:
        rows = authorship_rows(w)
        assert all(list(r) == AUTHORSHIP_COLUMNS for r in rows)
        orders = sorted({r["author_order"] for r in rows})
        assert orders == list(range(1, len(w["authorships"]) + 1))
        n_expected = sum(max(1, len(a["institutions"])) for a in w["authorships"])
        assert len(rows) == n_expected


def test_author_without_institution_gets_one_empty_row():
    w = {"id": "W1", "authorships": [{"author_position": "first",
                                      "author": {"id": "A1", "display_name": "X", "orcid": None},
                                      "is_corresponding": True, "institutions": [],
                                      "raw_affiliation_strings": ["Somewhere", "Else"]}]}
    rows = authorship_rows(w)
    assert len(rows) == 1
    assert rows[0]["institution_id"] is None
    assert rows[0]["raw_affiliation_strings"] == "Somewhere; Else"


def test_normalise_end_to_end(tmp_path):
    paths = Paths(tmp_path)
    data = fixture_b()["response"]
    d = paths.jy_dir("aer", 2020)
    d.mkdir(parents=True)
    (d / "page_0001.json.gz").write_bytes(gzip.compress(json.dumps(data).encode()))
    harvest.append_manifest(paths, {"journal_key": "aer", "source_id": "S23254222",
                                    "year": 2020, "expected_count": 5, "retrieved_count": 5,
                                    "unique_work_ids": 5, "n_pages": 1, "status": "complete",
                                    "finished_at": "2026-10-12T10:00:00Z"})
    w, a, problems = normalise(paths)
    assert problems == []
    assert len(w) == 5 and w["openalex_id"].is_unique
    assert set(w["raw_file"]) == {"data/raw/openalex/aer/2020/page_0001.json.gz"}
    assert paths.works.exists() and paths.authorships.exists()
