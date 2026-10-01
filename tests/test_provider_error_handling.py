import pytest

from backend import app as backend_app
from backend.llm_provider import OpenRouterProvider, ProviderRequestError


def test_openrouter_bad_request_preserves_status_for_diagnostics(monkeypatch):
    class Response:
        ok = False
        status_code = 400
        text = '{"error":{"message":"invalid request payload"}}'

    monkeypatch.setattr("requests.post", lambda *args, **kwargs: Response())
    provider = OpenRouterProvider("test-key", "test-model", "https://example.test", "tests")

    with pytest.raises(ProviderRequestError) as error:
        provider.generate("valid prompt")

    assert error.value.status_code == 400
    detail = backend_app._provider_error_detail(error.value)
    assert detail["code"] == "PROVIDER_REQUEST_INVALID"
    assert "rejected the request format" in detail["message"]


def test_provider_context_limit_error_is_not_reported_as_unknown():
    detail = backend_app._provider_error_detail(
        ProviderRequestError("Gemini", "input too long for this model's context window", 413)
    )

    assert detail["code"] == "PROMPT_TOO_LARGE"
    assert "context is too large" in detail["message"]


def test_gemini_3_uses_low_thinking_without_exposing_thoughts(monkeypatch):
    from backend.llm_provider import GeminiProvider

    captured = {}

    class Models:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return type("Response", (), {"text": "Concise answer.", "candidates": []})()

    provider = GeminiProvider.__new__(GeminiProvider)
    provider.client = type("Client", (), {"models": Models()})()
    provider.model = "gemini-3.6-flash"

    assert provider.generate("RAG prompt", max_output_tokens=2048) == "Concise answer."

    config = captured["config"]
    assert config.max_output_tokens == 2048
    assert config.thinking_config.thinking_level.name == "LOW"
    assert config.thinking_config.include_thoughts is False
    assert config.temperature is None
