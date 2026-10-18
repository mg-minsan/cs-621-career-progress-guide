"""
STEP 7b-2 - Mark E2 (course relevance).

    py src/score_e2.py            # agreement + precision@k per search mode
    py src/score_e2.py --tune     # also suggest STRONG/WEAK match thresholds
                                   (loads the re-ranker, ~1 min)

Labels
  AI file  (ChatGPT, all rows)        labels/E2_labeller_AI.xlsx
  A, B     (humans, ~50 sample rows)  labels/E2_labeller_A.xlsx, _B.xlsx

Gold label per row (state this rule in the report):
  * sample rows: majority vote of A, B and AI (3 voters, no ties)
  * other rows : the AI label
  The human-vs-AI agreement on the sample tells the reader how far to trust
  the AI-only rows.

Outputs: printed tables + results/e2_results.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
LABELS, EVALS, RESULTS = ROOT / "labels", ROOT / "evals", ROOT / "results"
MODES = ["bm25", "dense", "hybrid", "hybrid_rerank"]


def read_labels(name: str) -> dict[int, str]:
    path = LABELS / f"E2_labeller_{name}.xlsx"
    if not path.exists():
        return {}
    df = pd.read_excel(path, "labels")
    out = {}
    for rid, val in zip(df["row_id"], df["relevant"]):
        v = str(val).strip().upper()[:1] if pd.notna(val) else ""
        if v in {"Y", "N"}:
            out[int(rid)] = v
    return out


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


def gold_labels(ai, a, b, sample_ids) -> dict[int, str]:
    gold = dict(ai)
    for rid in sample_ids:
        votes = [lab[rid] for lab in (a, b, ai) if rid in lab]
        if len(votes) == 3:
            gold[rid] = "Y" if votes.count("Y") >= 2 else "N"
        elif votes and len(set(votes)) == 1:
            gold[rid] = votes[0]
    return gold


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


def main() -> None:
    ai1, ai2, a, b = read_labels("AI"), read_labels("AI2"), read_labels("A"), read_labels("B")
    # AI v2 (stricter prompt, written BEFORE the human labels existed) replaces v1 when present.
    # Both versions' agreement with the humans is reported, never just the better one.
    ai = ai2 or ai1
    if not ai:
        sys.exit("No AI labels found: fill labels/E2_labeller_AI.xlsx (or _AI2.xlsx) first.")
    sample = set(json.loads((EVALS / "e2_sample.json").read_text())["row_ids"]) \
        if (EVALS / "e2_sample.json").exists() else set()
    pool = json.loads((EVALS / "e2_pool.json").read_text())["skills"]
    sheet = pd.read_excel(LABELS / ("E2_labeller_AI2.xlsx" if ai2 else "E2_labeller_AI.xlsx"), "labels")
    row_pair = {int(r): (s, c) for r, s, c in zip(sheet["row_id"], sheet["skill"], sheet["course_ref"])}

    report: dict = {"ai_version_used_for_gold": "v2" if ai2 else "v1",
                    "rows_total": len(row_pair), "rows_ai_labelled": len(ai),
                    "sample_size": len(sample), "agreement": {}}
    yes = lambda lab: f"{sum(v == 'Y' for v in lab.values()) / len(lab):.0%} Y" if lab else "-"
    print(f"\nLABELS  AI v1: {len(ai1)} ({yes(ai1)})   AI v2: {len(ai2)} ({yes(ai2)})   "
          f"A: {len(a)} ({yes(a)})   B: {len(b)} ({yes(b)})   sample: {len(sample)}")
    print(f"Gold uses AI {report['ai_version_used_for_gold']} outside the sample.")
    print("\nAGREEMENT (on rows both labelled)")
    pairs_to_compare = [("A vs B (human-human)", a, b), ("AI v1 vs A", ai1, a), ("AI v1 vs B", ai1, b)]
    if ai2:
        pairs_to_compare += [("AI v2 vs A", ai2, a), ("AI v2 vs B", ai2, b), ("AI v1 vs AI v2", ai1, ai2)]
    for name, x, y in pairs_to_compare:
        k, n, raw = cohen_kappa(x, y)
        report["agreement"][name] = {"kappa": k, "n": n, "raw_agreement": raw}
        if n:
            print(f"  {name:22} kappa {k if k is None else round(k, 2)}   agree {raw:.0%}   (n={n})")
        else:
            print(f"  {name:22} (no overlapping labels yet)")

    gold = gold_labels(ai, a, b, sample)
    gold_by_pair = {row_pair[r]: v for r, v in gold.items() if r in row_pair}
    report["gold_relevant_rate"] = round(sum(v == "Y" for v in gold.values()) / len(gold), 3)
    print(f"\nPRECISION@k BY SEARCH MODE (share of shown courses that are relevant; "
          f"{report['gold_relevant_rate']:.0%} of pooled courses are relevant overall)")
    print(f"  {'mode':15} {'P@1':>6} {'P@3':>6} {'P@5':>6}")
    report["precision"] = {}
    for m in MODES:
        row = {f"P@{k}": precision_at_k(pool, gold_by_pair, m, k)[0] for k in (1, 3, 5)}
        report["precision"][m] = row
        print(f"  {m:15} " + " ".join(f"{v:6.2f}" for v in row.values()))

    if "--tune" in sys.argv:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from course_search import CourseIndex, _st_reranker
        text = {c["course_ref"]: c["search_text"] for c in CourseIndex(mode="bm25").courses}
        pairs = [(s, text[c], c, v) for (s, c), v in gold_by_pair.items() if c in text]
        report["thresholds"] = tune_thresholds(pairs, _st_reranker())
        t = report["thresholds"]
        print(f"\nTHRESHOLDS (re-ranker scores vs gold labels, n={t['n_pairs']})")
        print(f"  WEAK_MATCH   -> {t['suggested_WEAK_MATCH']}  (best Y/N split, accuracy {t['accuracy_at_weak']:.0%})")
        print(f"  STRONG_MATCH -> {t['suggested_STRONG_MATCH']}  (lowest score where >= 90% are relevant)")
        print("  Set them in PowerShell, e.g.  $env:CAREER_WEAK_MATCH = \"...\"  and report the values.")

    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "e2_results.json").write_text(json.dumps(report, indent=1, default=str))
    print(f"\nSaved results/e2_results.json")


if __name__ == "__main__":
    main()
