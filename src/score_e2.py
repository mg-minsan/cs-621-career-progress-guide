"""Score E2 using complete LLM judgments and majority voting on every row.

    python src/score_e2.py
    python src/score_e2.py --judges labels/e2_llm_judges_v2.json
    python src/score_e2.py --tune

Excel workbooks are readable copies; the saved judge JSON is the scoring input.
No human annotations or sampled-row voting are used.
Outputs: results/e2_llm_results.json
"""
from __future__ import annotations

import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LABELS, RESULTS = ROOT / "labels", ROOT / "results"
MODES = ["bm25", "dense", "hybrid", "hybrid_rerank"]


def cohen_kappa(x: dict[int, str], y: dict[int, str]) -> tuple[float | None, int, float | None]:
    """(kappa, n rows both labelled, raw % agreement)."""
    ids = sorted(set(x) & set(y))
    n = len(ids)
    if n == 0:
        return None, 0, None
    agree = sum(x[i] == y[i] for i in ids) / n
    px, py = sum(x[i] == "Y" for i in ids) / n, sum(y[i] == "Y" for i in ids) / n
    expected = px * py + (1 - px) * (1 - py)
    kappa = None if expected == 1 else (agree - expected) / (1 - expected)
    return kappa, n, agree


def precision_at_k(pool: dict, gold_by_pair: dict, mode: str, k: int) -> tuple[float, int]:
    """Mean over skills of (# relevant in the mode's top k) / (# labelled in top k)."""
    per_skill = []
    for skill, entries in pool.items():
        top = sorted((e for e in entries if mode in e["found_by"] and e["found_by"][mode] <= k),
                     key=lambda e: e["found_by"][mode])
        labs = [gold_by_pair[(skill, e["course_ref"])] for e in top
                if (skill, e["course_ref"]) in gold_by_pair]
        if labs:
            per_skill.append(sum(l == "Y" for l in labs) / len(labs))
    return (sum(per_skill) / len(per_skill) if per_skill else float("nan")), len(per_skill)


def tune_thresholds(pairs: list[tuple[str, str, str, str]], scorer) -> dict:
    """pairs: (skill, course_text, course_ref, gold). Scores each pair with the
    re-ranker, then finds (a) the cut-off that best separates Y from N
    -> WEAK_MATCH, (b) the lowest cut-off where >= 90% of courses above it are
    relevant -> STRONG_MATCH."""
    scores = [float(s) for s in scorer([(p[0], p[1][:1000]) for p in pairs])]
    golds = [p[3] for p in pairs]
    best = (0.0, None)
    strong = None
    for t10 in range(-50, 121, 5):
        t = t10 / 10
        pred = ["Y" if s >= t else "N" for s in scores]
        acc = sum(p == g for p, g in zip(pred, golds)) / len(golds)
        if acc > best[0]:
            best = (acc, t)
        above = [g for s, g in zip(scores, golds) if s >= t]
        if strong is None and len(above) >= 10 and sum(g == "Y" for g in above) / len(above) >= 0.9:
            strong = t
    if strong is not None and best[1] is not None:
        strong = max(strong, best[1])      # "strong" can never sit below "weak"
    return {"suggested_WEAK_MATCH": best[1], "accuracy_at_weak": round(best[0], 3),
            "suggested_STRONG_MATCH": strong, "n_pairs": len(pairs)}


def llm_consensus(data: dict) -> tuple[dict, dict]:
    """Require complete coverage and an odd number of identified model judges."""
    rows, judges = data["rows"], data["judges"]
    if not judges or len(judges) % 2 == 0:
        raise ValueError("Use an odd number of LLM judges (preferably 3) to avoid tied votes")
    ids = {str(r["row_id"]) for r in rows}
    if not ids or len(ids) != len(rows):
        raise ValueError("Empty or duplicate input row IDs")
    labels = {}
    for name, judge in judges.items():
        if judge.get("model") != name:
            raise ValueError(f"Judge identity mismatch: {name}")
        if set(judge["labels"]) != ids:
            raise ValueError(f"{name} has incomplete labels; resume e2_llm_judge.py without --limit")
        labels[name] = {int(rid): v["relevant"] for rid, v in judge["labels"].items()}
        if any(v not in {"Y", "N"} for v in labels[name].values()):
            raise ValueError(f"Invalid Y/N label from {name}")
    gold = {int(rid): "Y" if sum(lab[int(rid)] == "Y" for lab in labels.values()) > len(labels) / 2
            else "N" for rid in ids}
    return gold, labels


def score_llm_judges(path: Path, tune: bool = False) -> None:
    from itertools import combinations
    from e2_llm_judge import fingerprint

    data = json.loads(path.read_text())
    if data.get("method") != "llm_judges" or data.get("input_sha256") != fingerprint(data["rows"], data["pool"]):
        raise ValueError("Invalid LLM judge file or mismatched input fingerprint")
    gold, judges = llm_consensus(data)
    names = {name: judge.get("display_name", name) for name, judge in data["judges"].items()}
    row_pair = {int(r["row_id"]): (r["skill"], r["course_ref"]) for r in data["rows"]}
    pool = data["pool"]["skills"]
    expected = {(skill, e["course_ref"]) for skill, entries in pool.items() for e in entries}
    if set(row_pair.values()) != expected or len(row_pair) != len(expected):
        raise ValueError("Judge rows do not match saved retrieval pool")
    report = {"label_method": "llm_majority" if len(judges) > 1 else "single_llm_judge",
              "judges": list(names.values()), "judge_ids": list(judges),
              "rows_total": len(gold), "human_validated": False,
              "judge_metadata": {name: {k: v for k, v in judge.items() if k != "labels"}
                                 for name, judge in data["judges"].items()},
              "input_sha256": data["input_sha256"], "prompt": data["prompt"],
              "agreement": {}, "precision": {}}
    print(f"LLM-only labels: {len(gold)} rows, {len(judges)} judge(s); no human validation.")
    for name, labels in judges.items():
        print(f"  {names[name]}: {len(labels)}/{len(gold)} labels")
    print("\nAGREEMENT BETWEEN LLM JUDGES")
    for a, b in combinations(judges, 2):
        kappa, n, raw = cohen_kappa(judges[a], judges[b])
        pair = f"{names[a]} vs {names[b]}"
        report["agreement"][pair] = {"kappa": kappa, "n": n, "raw_agreement": raw}
        print(f"  {pair}: kappa={kappa}, agreement={raw:.1%} (n={n})")
    gold_by_pair = {row_pair[rid]: label for rid, label in gold.items()}
    print(f"  {'mode':15} {'P@1':>6} {'P@3':>6} {'P@5':>6}")
    for mode in MODES:
        metrics = {f"P@{k}": precision_at_k(pool, gold_by_pair, mode, k)[0] for k in (1, 3, 5)}
        report["precision"][mode] = metrics
        print(f"  {mode:15} " + " ".join(f"{v:6.2f}" for v in metrics.values()))
    report["disagreement_rows"] = sorted(rid for rid in gold
                                          if len({lab[rid] for lab in judges.values()}) > 1)
    if tune:
        from course_search import CourseIndex, _st_reranker
        text = {c["course_ref"]: c["search_text"] for c in CourseIndex(mode="bm25").courses}
        missing = {course for _, course in gold_by_pair if course not in text}
        if missing:
            raise ValueError("Courses from the saved judge pool are missing from the current database")
        pairs = [(skill, text[course], course, vote) for (skill, course), vote in gold_by_pair.items()]
        report["thresholds"] = tune_thresholds(pairs, _st_reranker())
        print("Suggested thresholds (not applied):", report["thresholds"])
    RESULTS.mkdir(exist_ok=True)
    output = RESULTS / "e2_llm_results.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Saved {output}; {len(report['disagreement_rows'])} rows have judge disagreement.")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judges", type=Path, default=LABELS / "e2_llm_judges.json",
                        help="Complete saved LLM judgments (default: labels/e2_llm_judges.json)")
    parser.add_argument("--tune", action="store_true", help="Suggest reranker thresholds using LLM consensus")
    args = parser.parse_args(argv)
    if not args.judges.exists():
        parser.error(f"No saved LLM judgments at {args.judges}. Run src/e2_llm_judge.py first.")
    score_llm_judges(args.judges, tune=args.tune)


if __name__ == "__main__":
    main()
