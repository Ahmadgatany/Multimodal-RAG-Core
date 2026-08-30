import pytest

from backend import app as backend_app


def test_create_and_decode_access_token():
    token = backend_app.create_access_token("user-42")
    payload = backend_app.decode_access_token(token)

    assert payload["sub"] == "user-42"
    assert payload["type"] == "access"
    assert payload["jti"]


def test_logout_invalidates_session_and_blacklist():
    backend_app.sessions.clear()
    token = backend_app.create_access_token("user-logout")
    backend_app._store_session_token(token, "user-logout")

    backend_app.logout_session_token(token)

    assert backend_app._touch_session(token) is None
    assert backend_app.is_token_revoked(token) is True

    with pytest.raises(Exception):
        backend_app.decode_access_token(token)
