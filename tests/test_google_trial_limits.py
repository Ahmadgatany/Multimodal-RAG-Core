import asyncio
from io import BytesIO

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from backend import app as backend_app


def test_free_questions_can_be_claimed_three_times_without_a_personal_key():
    backend_app._init_auth_storage()
    user_id = backend_app.uuid4().hex
    db = backend_app.SessionLocal()
    try:
        user = backend_app.User(
            id=user_id,
            username=f"google_{user_id}",
            password_hash="google-oauth-only",
            google_sub=f"test-{user_id}",
            email=f"{user_id}@example.test",
        )
        db.add(user)
        db.commit()

        assert backend_app._claim_trial_question(user_id) is True
        assert backend_app._claim_trial_question(user_id) is True
        assert backend_app._claim_trial_question(user_id) is True
        with pytest.raises(HTTPException) as error:
            backend_app._claim_trial_question(user_id)
        assert error.value.status_code == 402

        backend_app._release_trial_question(user_id)
        assert backend_app._claim_trial_question(user_id) is True
    finally:
        db.query(backend_app.User).filter(backend_app.User.id == user_id).delete()
        db.commit()
        db.close()


def test_upload_reader_rejects_any_file_over_two_mb():
    upload = UploadFile(filename="too-large.pdf", file=BytesIO(b"x" * (2 * 1024 * 1024 + 1)))

    with pytest.raises(HTTPException) as error:
        asyncio.run(backend_app._read_upload_with_limit(upload))

    assert error.value.status_code == 413


def test_provider_credit_errors_have_an_actionable_message():
    message = backend_app._provider_error_message(RuntimeError("HTTP 402: insufficient credit balance"))

    assert "credits are exhausted" in message


@pytest.mark.parametrize(
    ("provider_error", "expected_code", "message_fragment"),
    [
        ("404 NOT_FOUND: model gemini-example was not found", "MODEL_UNAVAILABLE", "model is unavailable"),
        ("requests.exceptions.ConnectTimeout: request timed out", "PROVIDER_TIMEOUT", "timed out"),
        ("503 service unavailable", "PROVIDER_UNREACHABLE", "temporarily unavailable"),
        ("Response blocked by safety policy", "CONTENT_BLOCKED", "safety policy"),
        ("Gemini returned an empty response", "EMPTY_MODEL_RESPONSE", "empty response"),
    ],
)
def test_provider_failures_have_safe_diagnostic_codes(provider_error, expected_code, message_fragment):
    detail = backend_app._provider_error_detail(RuntimeError(provider_error))

    assert detail["code"] == expected_code
    assert message_fragment in detail["message"]
