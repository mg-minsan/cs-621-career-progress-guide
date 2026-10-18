"""E1 auto labels: rules from the framework, checked on cases where the right answer is obvious."""
import json
import shutil
import sys
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import e1_auto_labels as a  # noqa: E402
import run_evals as rv  # noqa: E402

PERSONAS = {p["id"]: p for p in json.loads((ROOT / "evals" / "e1_personas.json").read_text())["personas"]}


def lab(pid):
    out = a.label(PERSONAS[pid])
    out.pop("_why")
    return out


def test_accounts_executive_ladder():
    l = lab("p02")
    assert l["current_role_id"] == 14
    assert 13 in l["acceptable_path_ids"]                      # Accountant / Senior AE: next rung
    assert {16, 19} <= set(l["must_not_path_ids"])             # Financial Controller, CFO: too senior
    assert l["goal_achievable"] == "n/a"


def test_goal_roles_and_impossible_goal():
    assert {723, 1226} <= set(lab("p01")["acceptable_path_ids"])   # data analyst roles
    l12 = lab("p12")
    assert l12["goal_achievable"] is False and l12["acceptable_path_ids"]


def test_customer_service_next_rung_is_senior_cs_not_sales():
    l = lab("p04")
    assert 567 in l["acceptable_path_ids"]                     # Customer Service Senior Executive
    assert not {560, 563} & set(l["acceptable_path_ids"])      # sideways sales jobs


def test_title_map_cases():
    assert lab("p10")["current_role_id"] in (1195, 1201, 1205) and 1187 in lab("p10")["acceptable_path_ids"]
    assert lab("p11")["current_role_id"] == 1056 and 1059 in lab("p11")["acceptable_path_ids"]
    assert 1221 in lab("p05")["acceptable_path_ids"]


def test_ambiguous_title_all_sectors_count():
    l = lab("p06")
    assert len([l["current_role_id"]] + l["current_role_alternatives"]) >= 4
    case = rv.Case("p06", PERSONAS["p06"], expected=l)
    r = rv.AgentResult(details={"e1": {"suggested_role_id": l["current_role_alternatives"][0],
                                       "path_ids": [l["acceptable_path_ids"][0]], "goal_status": "matched"}})
    assert rv.grade_e1(case, r) and r.checks["role_correct"]


def test_never_acceptable_and_forbidden_at_once():
    for pid in PERSONAS:
        l = lab(pid)
        assert not set(l["acceptable_path_ids"]) & set(l["must_not_path_ids"])
        assert l["current_role_id"] not in l["acceptable_path_ids"]


def test_make_writes_labels_and_audit_and_refuses_to_overwrite_human(tmp_path, monkeypatch):
    pf = tmp_path / "e1_personas.json"
    shutil.copy(ROOT / "evals" / "e1_personas.json", pf)
    monkeypatch.setattr(a, "PERSONAS", pf)
    monkeypatch.setattr(a, "AUDIT", tmp_path / "audit.xlsx")
    monkeypatch.setattr(a, "ROOT", tmp_path)
    a.make()
    data = json.loads(pf.read_text())
    assert all(p["labels"]["source"].startswith("auto") for p in data["personas"])
    ws = load_workbook(tmp_path / "audit.xlsx")["audit"]
    assert ws.max_row > 50
    monkeypatch.setattr(rv, "EVALS", tmp_path)
    cases, total = rv.load_e1(None)
    assert len(cases) == total == 12                           # every persona now runs
    data["personas"][0]["labels"]["source"] = "team: A+B"      # pretend a human labelled p01
    pf.write_text(json.dumps(data))
    (tmp_path / "audit.xlsx").unlink()
    try:
        a.make()
        raise AssertionError("should refuse to overwrite human labels")
    except SystemExit:
        pass
