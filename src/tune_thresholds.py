"""
Fix 6: tune the course-match thresholds on HALF of the E2 labels, then test them on the other half.

    py src/tune_thresholds.py        # needs the re-ranker model (setup downloads it); no API calls, ~1 min

The numbers it tunes (all re-ranker scores, cross-encoder/ms-marco-MiniLM-L-6-v2):
  RERANK_GOOD   course_search.py  below this a course is not shown at all ("no strong match")
  WEAK_MATCH    plan_rules.py     below this the chosen course is shown as "weak match - check it"
  STRONG_MATCH  plan_rules.py     a cheaper runner-up may only win on price if it is at least this
Until now all three were placeholders read off one run (0.0 / 5.0 / 8.0).

Design (decided before looking at any score):
  - Split by SKILL, not by row (about half the skills each): a row-level split would put the same
    skill's courses on both sides and flatter the test. Skills are dealt so both halves get a
    similar number of irrelevant pairs (a plain shuffle gave the tuning half only 4 of 16).
  - Tune only on rows where all 3 AI judges agree. The human check (Fix 5) showed the split-vote
    rows are genuinely ambiguous (4 of the 6 "Unsure" answers), so they are not gold for tuning.
    The test half is reported both ways.
  - Gold is 85% "relevant", so raw accuracy would reward a threshold that flags nothing.
    WEAK_MATCH maximises BALANCED accuracy (mean of: relevant kept, irrelevant flagged).
  - RERANK_GOOD hides courses outright, so it is cautious: the highest cut that still keeps
    >= 95% of relevant courses. STRONG_MATCH: the lowest cut where >= 90% of courses above it
    are relevant (at least 10 courses). Order is enforced: RERANK_GOOD <= WEAK <= STRONG.
  - CLOSE_MARGIN (how close two scores must be for price to decide) is NOT tuned: these labels
    say whether one course is relevant, not which of two is better, so they cannot tune it.

Nothing is applied automatically. Read results/thresholds.md first; adopt the values only if
they beat the placeholders on the TEST half.
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEED = 621
PLACEHOLDERS = {"RERANK_GOOD": 0.0, "WEAK_MATCH": 5.0, "STRONG_MATCH": 8.0}
GRID = [t / 2 for t in range(-24, 25)]              # -12.0 .. 12.0 in steps of 0.5


def load_pairs() -> list[dict]:
    data = json.loads((ROOT / "labels" / "e2_llm_judges.json").read_text(encoding="utf-8"))
    votes = [{int(k): v["relevant"] for k, v in j["labels"].items()} for j in data["judges"].values()]
    con = sqlite3.connect(ROOT / "data" / "careers.db")
    text = dict(con.execute("SELECT course_ref, search_text FROM courses"))
    pairs = []
    for r in data["rows"]:
        y = sum(v[r["row_id"]] == "Y" for v in votes)
        if r["course_ref"] not in text:
            raise ValueError(f"{r['course_ref']} is in the E2 labels but not in data/careers.db")
        pairs.append({"row_id": r["row_id"], "skill": r["skill"], "course_ref": r["course_ref"],
                      "text": (text[r["course_ref"]] or "")[:1000],          # what the app scores
                      "gold": "Y" if y > len(votes) / 2 else "N", "unanimous": y in (0, len(votes))})
    return pairs


def split_by_skill(pairs: list[dict], seed: int = SEED) -> tuple[list[dict], list[dict]]:
    """Whole skills go to one side. Irrelevant pairs are rare (16 unanimous) and bunched in a
    few skills, so a plain shuffle gave the tuning half only 4. Skills are dealt like cards
    (most irrelevant pairs first, snake order: tune, test, test, tune, ...) so both halves get
    a similar number. Uses labels only, never scores; ties broken by a seeded shuffle."""
    skills = sorted({p["skill"] for p in pairs})
    random.Random(seed).shuffle(skills)
    n_bad = {s: sum(p["skill"] == s and p["gold"] == "N" and p["unanimous"] for p in pairs) for s in skills}
    skills.sort(key=lambda s: -n_bad[s])                       # stable: keeps the shuffle for ties
    tune_skills = {s for i, s in enumerate(skills) if i % 4 in (0, 3)}
    return ([p for p in pairs if p["skill"] in tune_skills], [p for p in pairs if p["skill"] not in tune_skills])


def at(rows: list[dict], t: float) -> dict:
    """Treat score >= t as 'relevant'. Recall = relevant kept; tnr = irrelevant caught."""
    tp = sum(r["score"] >= t and r["gold"] == "Y" for r in rows)
    fp = sum(r["score"] >= t and r["gold"] == "N" for r in rows)
    fn = sum(r["score"] < t and r["gold"] == "Y" for r in rows)
    tn = sum(r["score"] < t and r["gold"] == "N" for r in rows)
    rec = tp / (tp + fn) if tp + fn else None
    tnr = tn / (tn + fp) if tn + fp else None
    prec = tp / (tp + fp) if tp + fp else None
    bal = (rec + tnr) / 2 if rec is not None and tnr is not None else None
    return {"n": len(rows), "relevant_kept": rec, "irrelevant_caught": tnr, "precision_above": prec,
            "balanced_acc": bal, "tp": tp, "fp": fp, "fn": fn, "tn": tn}


def tune(rows: list[dict]) -> dict:
    weak = max(GRID, key=lambda t: ((at(rows, t)["balanced_acc"] or 0), -t))
    keep = [t for t in GRID if (at(rows, t)["relevant_kept"] or 0) >= 0.95]
    good = min(max(keep) if keep else GRID[0], weak)
    strong = next((t for t in GRID if at(rows, t)["tp"] + at(rows, t)["fp"] >= 10
                   and (at(rows, t)["precision_above"] or 0) >= 0.9), None)
    strong = max(strong, weak) if strong is not None else None
    return {"RERANK_GOOD": good, "WEAK_MATCH": weak, "STRONG_MATCH": strong}


def _fmt(x) -> str:
    return "n/a" if x is None else f"{x:.0%}"


def report(pairs: list[dict]) -> tuple[dict, str]:
    tune_rows, test_rows = split_by_skill(pairs)
    fit = [r for r in tune_rows if r["unanimous"]]
    chosen = tune(fit)
    test_u = [r for r in test_rows if r["unanimous"]]
    lines = ["# Threshold tuning (Fix 6)", "",
             f"Re-ranker scores for all {len(pairs)} E2 pairs (skill vs the first 1,000 characters the app scores). "
             f"Split by skill (seed {SEED}): tune = {len({r['skill'] for r in tune_rows})} skills / {len(tune_rows)} pairs "
             f"({len(fit)} unanimous, used to fit), test = {len({r['skill'] for r in test_rows})} skills / "
             f"{len(test_rows)} pairs ({len(test_u)} unanimous).",
             f"Irrelevant (N) pairs: {sum(r['gold'] == 'N' for r in fit)} in the tuning set, "
             f"{sum(r['gold'] == 'N' for r in test_u)} in the unanimous test set. Small: read counts, not just %.", "",
             "| Threshold | placeholder | tuned |", "|---|---|---|"]
    for k in PLACEHOLDERS:
        lines.append(f"| {k} | {PLACEHOLDERS[k]} | {chosen[k]} |")
    lines += ["", "## Held-out test half: does the tuned value beat the placeholder?", "",
              "| Threshold | value | rows | relevant kept | irrelevant caught | precision above | balanced acc |",
              "|---|---|---|---|---|---|---|"]
    out = {"seed": SEED, "tuned": chosen, "placeholders": PLACEHOLDERS, "test": {}}
    for k in PLACEHOLDERS:
        for label, val in (("placeholder", PLACEHOLDERS[k]), ("tuned", chosen[k])):
            if val is None:
                continue
            for name, rows in (("unanimous", test_u), ("all", test_rows)):
                m = at(rows, val)
                out["test"][f"{k}|{label}|{name}"] = {"value": val, **m}
                lines.append(f"| {k} ({label}) | {val} | {name} {m['n']} | {_fmt(m['relevant_kept'])} "
                             f"({m['tp']}/{m['tp'] + m['fn']}) | {_fmt(m['irrelevant_caught'])} ({m['tn']}/{m['tn'] + m['fp']}) "
                             f"| {_fmt(m['precision_above'])} | {_fmt(m['balanced_acc'])} |")
    lines += ["", "What each column means for the user:",
              "- RERANK_GOOD: *relevant kept* = good courses still shown; *irrelevant caught* = bad ones hidden.",
              "- WEAK_MATCH: *irrelevant caught* = bad picks that get the 'weak match - check it' warning.",
              "- STRONG_MATCH: *precision above* = how often a course allowed to win on price is really relevant.",
              "", "CLOSE_MARGIN is not tuned: relevance labels cannot say which of two relevant courses is better."]
    return out, "\n".join(lines) + "\n"


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from course_search import _st_reranker
    pairs = load_pairs()
    print(f"Scoring {len(pairs)} pairs with the re-ranker (no API calls)...")
    scores = _st_reranker()([(p["skill"], p["text"]) for p in pairs])
    for p, s in zip(pairs, scores):
        p["score"] = round(float(s), 3)
    out, md = report(pairs)
    out["scores"] = {p["row_id"]: p["score"] for p in pairs}
    res = ROOT / "results"
    res.mkdir(exist_ok=True)
    (res / "thresholds.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    (res / "thresholds.md").write_text(md, encoding="utf-8")
    print(md)
    print("Written to results/thresholds.md and results/thresholds.json (nothing applied).")


if __name__ == "__main__":
    main()
