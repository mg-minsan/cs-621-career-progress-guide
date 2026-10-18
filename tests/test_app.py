"""Step 6: the Streamlit page, driven end to end offline (rules mode, no API)."""
import os
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("CAREER_SEARCH_MODE", "bm25")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CAREER_NO_DOTENV", "1")          # never pick up a real key from .env in tests


def btn(at, label):
    return [b for b in at.button if b.label == label][0]


def test_all_three_checkpoints_then_refresh_resumes():
    at = st_testing.AppTest.from_file(APP, default_timeout=180).run()
    at.text_input[0].input("Accounts Executive")
    at.text_input[1].input("move into data analyst")
    at.number_input[0].set_value(41)
    btn(at, "Make my plan ✨").click().run()
    assert at.subheader[0].value.startswith("Which of these")          # confirm_role
    at.radio[0].set_value(14)
    btn(at, "Yes, this is my job").click().run()
    assert at.subheader[0].value.startswith("Where would you")         # choose_path
    btn(at, "Plan this path").click().run()
    assert "→" in at.subheader[0].value                                # approve_plan
    btn(at, "Approve plan").click().run()
    assert "You approved this plan" in at.success[0].value
    tid = at.query_params["thread"]
    tid = tid[0] if isinstance(tid, list) else tid
    again = st_testing.AppTest.from_file(APP, default_timeout=180)
    again.query_params["thread"] = tid                                 # a browser refresh
    again.run()
    assert "You approved this plan" in again.success[0].value          # resumed from the checkpointer


def test_impossible_credit_balance_is_asked_again():
    at = st_testing.AppTest.from_file(APP, default_timeout=180).run()
    at.text_input[0].input("Accounts Executive")
    at.number_input[0].set_value(30)
    at.number_input[1].set_value(99999.0)
    btn(at, "Make my plan ✨").click().run()
    assert "credit_balance" in at.info[0].value                        # ask_missing_info
    at.checkbox[0].check()
    btn(at, "Continue").click().run()
    assert at.subheader[0].value.startswith("Which of these")
