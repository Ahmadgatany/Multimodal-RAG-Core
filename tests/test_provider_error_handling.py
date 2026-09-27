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
