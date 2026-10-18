import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from score_e2 import cohen_kappa, gold_labels, precision_at_k  # noqa: E402


def test_kappa_perfect_and_chance():
    x = {1: "Y", 2: "N", 3: "Y", 4: "N"}
    assert cohen_kappa(x, x)[0] == 1.0
    assert cohen_kappa(x, {1: "N", 2: "Y", 3: "N", 4: "Y"})[0] == -1.0


def test_gold_is_majority_on_sample_and_ai_elsewhere():
    ai, a, b = {1: "Y", 2: "Y"}, {1: "N"}, {1: "N"}
    assert gold_labels(ai, a, b, {1}) == {1: "N", 2: "Y"}


def test_precision_counts_only_the_modes_top_k():
    pool = {"S": [{"course_ref": "c1", "found_by": {"bm25": 1}},
                  {"course_ref": "c2", "found_by": {"bm25": 2, "dense": 1}}]}
    gold = {("S", "c1"): "Y", ("S", "c2"): "N"}
    assert precision_at_k(pool, gold, "bm25", 1)[0] == 1.0
    assert precision_at_k(pool, gold, "bm25", 3)[0] == 0.5
    assert precision_at_k(pool, gold, "dense", 1)[0] == 0.0
