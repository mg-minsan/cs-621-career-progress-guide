import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from score_e2 import cohen_kappa, precision_at_k  # noqa: E402
from score_e2 import llm_consensus
import pytest


def test_kappa_perfect_and_chance():
    x = {1: "Y", 2: "N", 3: "Y", 4: "N"}
    assert cohen_kappa(x, x)[0] == 1.0
    assert cohen_kappa(x, {1: "N", 2: "Y", 3: "N", 4: "Y"})[0] == -1.0


def test_precision_counts_only_the_modes_top_k():
    pool = {"S": [{"course_ref": "c1", "found_by": {"bm25": 1}},
                  {"course_ref": "c2", "found_by": {"bm25": 2, "dense": 1}}]}
    gold = {("S", "c1"): "Y", ("S", "c2"): "N"}
    assert precision_at_k(pool, gold, "bm25", 1)[0] == 1.0
    assert precision_at_k(pool, gold, "bm25", 3)[0] == 0.5
    assert precision_at_k(pool, gold, "dense", 1)[0] == 0.0


def test_llm_votes_all_rows_without_human_labels():
    data = {"rows": [{"row_id": 1}, {"row_id": 2}], "judges": {
        model: {"model": model, "labels": {"1": {"relevant": a}, "2": {"relevant": b}}}
        for model, a, b in [("m1", "Y", "N"), ("m2", "N", "Y"), ("m3", "N", "N")]}}
    gold, labels = llm_consensus(data)
    assert gold == {1: "N", 2: "N"}
    assert len(labels) == 3
    del data["judges"]["m1"]["labels"]["2"]
    with pytest.raises(ValueError, match="incomplete"):
        llm_consensus(data)


def test_llm_even_judge_count_is_rejected():
    with pytest.raises(ValueError, match="odd number"):
        llm_consensus({"rows": [{"row_id": 1}], "judges": {"m1": {}, "m2": {}}})


def test_llm_scoring_uses_saved_pool_and_majority(tmp_path, monkeypatch):
    import json
    import score_e2
    from e2_llm_judge import fingerprint

    rows = [{"row_id": 1, "skill": "Budgeting", "course_ref": "c1"}]
    pool = {"skills": {"Budgeting": [{"course_ref": "c1", "found_by": {
        mode: 1 for mode in score_e2.MODES}}]}}
    data = {"method": "llm_judges", "rows": rows, "pool": pool, "prompt": "test rubric",
            "input_sha256": fingerprint(rows, pool), "judges": {
                name: {"model": name, "labels": {"1": {"relevant": vote}}}
                for name, vote in [("a", "Y"), ("b", "Y"), ("c", "N")]}}
    source = tmp_path / "judges.json"
    source.write_text(json.dumps(data))
    monkeypatch.setattr(score_e2, "RESULTS", tmp_path)
    monkeypatch.setattr(score_e2, "LABELS", tmp_path)
    source.rename(tmp_path / "e2_llm_judges.json")
    source = tmp_path / "e2_llm_judges.json"
    score_e2.main([])
    report = json.loads((tmp_path / "e2_llm_results.json").read_text())
    assert report["precision"]["hybrid_rerank"]["P@1"] == 1.0
    assert report["disagreement_rows"] == [1]
    assert report["human_validated"] is False
    assert len(report["agreement"]) == 3
    data["rows"][0]["skill"] = "Changed evidence"
    source.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="fingerprint"):
        score_e2.score_llm_judges(source)
