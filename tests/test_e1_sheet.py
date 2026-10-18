"""E1 sheet: make -> fill -> load round trip, on temporary copies."""
import json
import shutil
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import e1_sheet  # noqa: E402


def test_round_trip(tmp_path, monkeypatch):
    personas = tmp_path / "e1_personas.json"
    data = json.loads((ROOT / "evals" / "e1_personas.json").read_text(encoding="utf-8"))
    for p in data["personas"]:          # start from blank labels, even if the real file is labelled
        p["labels"] = {"current_role_id": None, "acceptable_path_ids": [], "must_not_path_ids": [],
                       "goal_achievable": None, "source": ""}
    personas.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(e1_sheet, "PERSONAS", personas)
    monkeypatch.setattr(e1_sheet, "SHEET", tmp_path / "E1_labels.xlsx")
    e1_sheet.make()
    wb = load_workbook(tmp_path / "E1_labels.xlsx")
    ws, ps = wb["roles"], wb["personas"]
    listed = {r[2] for r in ws.iter_rows(min_row=2, values_only=True) if r[0] == "p01"}
    assert {14, 723} <= listed                      # current job + goal both listed
    for row in ws.iter_rows(min_row=2):
        if row[0].value == "p01" and row[2].value == 14:
            row[7].value = "Y"
        if row[0].value == "p01" and row[2].value in (13, 723):
            row[8].value = "Y"
    ps["C2"], ps["D2"], ps["F2"] = "Y", "Accountancy sector guide (test)", "1226"
    wb.save(tmp_path / "E1_labels.xlsx")
    e1_sheet.load()
    lab = json.loads(personas.read_text())["personas"][0]["labels"]
    assert lab["current_role_id"] == 14 and lab["acceptable_path_ids"] == [13, 723, 1226]
    assert lab["goal_achievable"] is True
    others = json.loads(personas.read_text())["personas"][1]["labels"]
    assert others["current_role_id"] is None          # untouched personas stay unlabelled
