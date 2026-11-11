import pytest
from app.agent.llm import (
    DEFAULT_MODELS,
    _format_provider_error,
    extract_json,
    get_client,
    model_name,
)
from app.core.config import settings


def test_extract_json_clean():
    data = extract_json('{"summary": "Clean code", "quality_score": 95}')
    assert data["summary"] == "Clean code"
    assert data["quality_score"] == 95


def test_extract_json_with_code_fence():
    text = '```json\n{"fixed_code": "def f(): return 1"}\n```'
    data = extract_json(text)
    assert data["fixed_code"] == "def f(): return 1"


def test_extract_json_with_braces_in_preamble():
    text = 'Note: The function f() { return 1; } has issues.\nHere is the json:\n{"summary": "Issues found", "quality_score": 70}'
    data = extract_json(text)
    assert data["summary"] == "Issues found"
    assert data["quality_score"] == 70


def test_extract_json_with_braces_in_postamble():
    text = 'Here is the JSON:\n{"summary": "Good", "quality_score": 90}\nFor comparison check: {"ref": 123}'
    data = extract_json(text)
    assert data["summary"] == "Good"
    assert data["quality_score"] == 90


def test_extract_json_with_raw_control_characters():
    text = '{"test_code": "def test_f():\n    assert 1 == 1\n    return True\n"}'
    data = extract_json(text)
    assert "def test_f():" in data["test_code"]
    assert "return True" in data["test_code"]


def test_extract_json_with_escaped_quotes_and_backslashes():
    text = r'{"fix": "re.sub(r\"\\bword\\b\", \"\", text)"}'
    data = extract_json(text)
    assert r"\bword\b" in data["fix"]


def test_extract_json_invalid_raises():
    with pytest.raises(ValueError):
        extract_json("This is purely conversational text with no JSON at all.")


def test_model_name_resolution(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "groq")
    monkeypatch.setattr(settings, "groq_model", "")
    monkeypatch.setattr(settings, "llm_model", "")
    assert model_name("groq") == DEFAULT_MODELS["groq"]

    monkeypatch.setattr(settings, "groq_model", "custom-groq-model")
    assert model_name("groq") == "custom-groq-model"

    monkeypatch.setattr(settings, "groq_model", "")
    monkeypatch.setattr(settings, "llm_model", "fallback-model")
    assert model_name("groq") == "fallback-model"


def test_get_client_caching(monkeypatch):
    monkeypatch.setattr(settings, "ollama_base_url", "http://localhost:11434/v1")
    c1 = get_client("ollama")
    c2 = get_client("ollama")
    assert c1 is c2


def test_format_provider_error():
    class FakeConnectError(Exception):
        pass

    ollama_err = _format_provider_error("ollama", FakeConnectError("Connection refused"))
    assert "ollama serve" in ollama_err

    class FakeAuthError(Exception):
        pass

    auth_err = _format_provider_error("groq", FakeAuthError("401 Unauthorized"))
    assert "API key" in auth_err
