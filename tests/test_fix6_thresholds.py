"""Fix 6: the tuning split is leak-free and balanced; tuned values keep their order.
Uses a stand-in scorer (the real re-ranker runs on a teammate's machine), so no model, no API."""
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import tune_thresholds as T  # noqa: E402


def _scored(seed=1):
    pairs, rng = T.load_pairs(), random.Random(seed)
    for p in pairs:
        p["score"] = rng.gauss(6, 3) if p["gold"] == "Y" else rng.gauss(-1, 3)
    return pairs


def test_split_is_by_skill_reproducible_and_balanced():
    pairs = T.load_pairs()
    a, b = T.split_by_skill(pairs)
    assert not {p["skill"] for p in a} & {p["skill"] for p in b}          # no skill on both sides
    assert len(a) + len(b) == len(pairs) == 186
    assert [p["row_id"] for p in a] == [p["row_id"] for p in T.split_by_skill(T.load_pairs())[0]]
    bad = [sum(p["gold"] == "N" and p["unanimous"] for p in h) for h in (a, b)]
    assert min(bad) >= 6 and abs(bad[0] - bad[1]) <= 3                     # was 4 vs 12 before


def test_tuned_values_keep_their_order():
    for seed in range(5):
        t = T.tune([p for p in T.split_by_skill(_scored(seed))[0] if p["unanimous"]])
        assert t["RERANK_GOOD"] <= t["WEAK_MATCH"]
        assert t["STRONG_MATCH"] is None or t["WEAK_MATCH"] <= t["STRONG_MATCH"]


def test_split_vote_rows_are_never_used_to_fit(monkeypatch):
    seen = []
    real = T.tune
    monkeypatch.setattr(T, "tune", lambda rows: (seen.extend(rows), real(rows))[1])
    T.report(_scored())
    assert seen and all(r["unanimous"] for r in seen)


def test_metric_counts():
    rows = [{"score": 3, "gold": "Y"}, {"score": 1, "gold": "Y"}, {"score": 2, "gold": "N"}, {"score": 0, "gold": "N"}]
    m = T.at(rows, 1.5)
    assert (m["tp"], m["fn"], m["fp"], m["tn"]) == (1, 1, 1, 1) and m["balanced_acc"] == 0.5
