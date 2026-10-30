"""Fix 5: the human-check sheet is blind, stratified and reproducible; the scorer's maths is right."""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import make_human_check as M  # noqa: E402
from score_human_check import kappa  # noqa: E402


def test_e2_sample_is_stratified_and_reproducible():
    a, b = M.e2_sample(random.Random(M.SEED)), M.e2_sample(random.Random(M.SEED))
    assert [r["row_id"] for r in a] == [r["row_id"] for r in b]
    strata = {r["row_id"]: k for k, rs in M.e2_strata().items() for r in rs}
    got = {k: sum(strata[r["row_id"]] == k for r in a) for k in M.E2_PLAN}
    assert got == M.E2_PLAN and len({r["row_id"] for r in a}) == 25


def test_sheet_is_blind(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "OUT", tmp_path / "hc.xlsx")
    M.main()
    from openpyxl import load_workbook
    text = " ".join(str(c) for ws in load_workbook(tmp_path / "hc.xlsx").worksheets
                    for row in ws.iter_rows(values_only=True) for c in row if c)
    data = json.loads((ROOT / "labels" / "e2_llm_judges.json").read_text(encoding="utf-8"))
    reasons = [v["reason"] for j in data["judges"].values() for v in j["labels"].values() if len(v["reason"]) > 30]
    assert not any(r in text for r in reasons)                       # no judge reason leaks
    assert "unanimous" not in text and "split" not in text           # nor the stratum


def test_kappa():
    assert kappa([("Y", "Y"), ("N", "N")]) == 1.0
    assert kappa([("Y", "N"), ("N", "Y")]) == -1.0
    assert kappa([]) is None
