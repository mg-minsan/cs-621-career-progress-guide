"""Verify the DeepSeek request without network access or real credentials."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_deepseek_disables_thinking_and_saves_parsed_vote(tmp_path, monkeypatch):
    pytest.importorskip("langchain_deepseek")
    import httpx
    import langchain.chat_models
    import e2_llm_judge
    import settings

    sent = []

    def respond(request):
        payload = json.loads(request.content)
        sent.append(payload)
        return httpx.Response(200, json={
            "id": "test", "object": "chat.completion", "created": 0,
            "model": "deepseek-flash", "choices": [{"index": 0,
                "finish_reason": "tool_calls", "message": {"role": "assistant", "content": "",
                    "tool_calls": [{"id": "vote", "type": "function", "function": {
                        "name": "Judgment", "arguments": json.dumps({
                            "relevant": "Y", "reason": "Teaches budget preparation."})}}]}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})

    original = langchain.chat_models.init_chat_model
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        def init(model, **kwargs):
            return original(model, api_key="test-not-a-real-key", http_client=client, **kwargs)

        monkeypatch.setattr(langchain.chat_models, "init_chat_model", init)
        monkeypatch.setattr(settings, "load_env", lambda: None)
        monkeypatch.setattr(e2_llm_judge, "read_pairs", lambda *_: [{
            "row_id": 1, "skill": "Budgeting", "course_ref": "c1",
            "skill_description": "Prepare budgets", "course_title": "Budgets",
            "course_text": "Learn to prepare budgets"}])
        pool = tmp_path / "pool.json"
        pool.write_text(json.dumps({"skills": {}}))
        output = tmp_path / "labels.json"
        e2_llm_judge.main(["--models", "deepseek:deepseek-flash", "--pool", str(pool),
                           "--output", str(output), "--limit", "1"])

    assert len(sent) == 1
    assert sent[0]["thinking"] == {"type": "disabled"}
    assert sent[0]["tool_choice"]["function"]["name"] == "Judgment"
    saved = json.loads(output.read_text())["judges"]["deepseek:deepseek-flash"]
    assert saved["thinking"] == "disabled"
    assert saved["labels"]["1"]["relevant"] == "Y"
