"""
Fix 5: score the blind human check against the AI judges (E2) and the E1 rules.

    py src/score_human_check.py         # reads labels/human_check.xlsx, writes results/human_check.md

E2: agreement between the person and the AI majority, per stratum and re-weighted to the
real mix of the 186 pairs (the sample over-draws split and unanimous-N rows on purpose);
Cohen's kappa; agreement with each judge on its own. Unsure answers are left out and counted.
E1: share of rule-made labels the person agrees with, per label kind.
Small samples: report the counts, not just percentages.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_human_check import OUT, ROOT, e2_strata  # noqa: E402

RESULT = ROOT / "results" / "human_check.md"


def kappa(pairs: list[tuple[str, str]]) -> float | None:
    """Cohen's kappa for two raters on Y/N."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a == "Y" for a, _ in pairs) / n, sum(b == "Y" for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe == 1 else (po - pe) / (1 - pe)


def _answers(ws) -> list[tuple]:
    rows = [r for r in ws.iter_rows(min_row=2, values_only=True) if r and r[0] is not None]
    return [(r[1], (r[5] or "").strip(), (r[6] or "")) for r in rows]


def score(path: Path = OUT) -> str:
    wb = load_workbook(path)
    data = json.loads((ROOT / "labels" / "e2_llm_judges.json").read_text(encoding="utf-8"))
    judges = {n: {int(k): v["relevant"] for k, v in j["labels"].items()} for n, j in data["judges"].items()}
    rows = {r["row_id"]: r for r in data["rows"]}
    strata = {r["row_id"]: k for k, rs in e2_strata().items() for r in rs}
    share = {k: len(rs) / len(rows) for k, rs in e2_strata().items()}
    majority = {rid: "Y" if sum(j[rid] == "Y" for j in judges.values()) > len(judges) / 2 else "N" for rid in rows}

    e2 = _answers(wb["E2 courses"])
    blank = [rid for rid, a, _ in e2 if not a]
    if blank:
        sys.exit(f"E2: {len(blank)} row(s) still blank (row_ids {blank}). Fill them (or choose Unsure) first.")
    sure = [(int(rid), a) for rid, a, _ in e2 if a in ("Y", "N")]
    lines = ["# Human check (Fix 5)", "",
             f"One person, blind to the AI labels. Sample: {len(e2)} E2 pairs (stratified), "
             f"{len(_answers(wb['E1 roles']))} E1 labels. Unsure answers are excluded and counted.", "",
             "## E2: does the course teach the skill? (person vs AI-judge majority)", "",
             "| Stratum | in all 186 | checked | agree | agreement |", "|---|---|---|---|---|"]
    weighted = 0.0
    for k in ("unanimous_Y", "unanimous_N", "split"):
        got = [(rid, a) for rid, a in sure if strata[rid] == k]
        agree = sum(a == majority[rid] for rid, a in got)
        rate = agree / len(got) if got else None
        if rate is not None:
            weighted += share[k] * rate
        lines.append(f"| {k} | {share[k]:.0%} | {len(got)} | {agree} | "
                     f"{'n/a' if rate is None else f'{rate:.0%}'} |")
    raw = sum(a == majority[rid] for rid, a in sure)
    k = kappa([(a, majority[rid]) for rid, a in sure])
    lines += ["",
              f"- **Re-weighted agreement (estimate for all 186 pairs): {weighted:.0%}**",
              f"- Raw agreement on the sample: {raw}/{len(sure)}; Cohen's kappa {'n/a' if k is None else f'{k:.2f}'} "
              "(kappa is low when one answer dominates, so read it with the table)",
              f"- Unsure: {sum(a == 'Unsure' for _, a, _ in e2)}",
              f"- Person said Y on {sum(a == 'Y' for _, a in sure)}/{len(sure)}; "
              f"AI majority said Y on {sum(majority[rid] == 'Y' for rid, _ in sure)}/{len(sure)} of the same rows", "",
              "| Judge | agrees with the person |", "|---|---|"]
    for name, lab in judges.items():
        lines.append(f"| {data['judges'][name].get('display_name', name)} | "
                     f"{sum(a == lab[rid] for rid, a in sure)}/{len(sure)} |")
    dis = [(rid, a) for rid, a in sure if a != majority[rid]]
    if dis:
        lines += ["", "Disagreements (person vs AI majority):", ""]
        for rid, a in dis:
            r = rows[rid]
            lines.append(f"- row {rid}: *{r['skill']}* / {r['course_title'][:70]} : person **{a}**, "
                         f"AI {majority[rid]} ({strata[rid]})")

    e1 = _answers(wb["E1 roles"])
    blank = [i for i, a, _ in e1 if not a]
    if blank:
        sys.exit(f"E1: {len(blank)} row(s) still blank. Fill them (or choose Unsure) first.")
    lines += ["", "## E1: rule-made labels (person agrees?)", "",
              "| Label kind | checked | agree | disagree | unsure |", "|---|---|---|---|---|"]
    for kind in ("current", "acceptable_next", "must_not"):
        got = [a for i, a, _ in e1 if i.split("|")[1] == kind]
        lines.append(f"| {kind} | {len(got)} | {got.count('Agree')} | {got.count('Disagree')} | {got.count('Unsure')} |")
    sure1 = [a for _, a, _ in e1 if a in ("Agree", "Disagree")]
    lines.append(f"\n- **Overall: {sure1.count('Agree')}/{len(sure1)} rule labels agreed with**")
    for i, a, note in e1:
        if a == "Disagree":
            pid, kind, rid = i.split("|")
            lines.append(f"- disagree: {pid} {kind} role {rid}" + (f" ({note})" if note else ""))
    md = "\n".join(lines) + "\n"
    RESULT.parent.mkdir(exist_ok=True)
    RESULT.write_text(md, encoding="utf-8")
    return md


if __name__ == "__main__":
    print(score())
    print(f"Written to {RESULT.relative_to(ROOT)}")
