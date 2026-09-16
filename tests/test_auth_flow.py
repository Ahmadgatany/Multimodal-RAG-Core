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


def test_refresh_rotation_revokes_previous_refresh_token():
    backend_app.sessions.clear()
    backend_app.revoked_tokens.clear()

    old_refresh = backend_app.create_refresh_token("user-rotation")
    old_payload = backend_app.decode_refresh_token(old_refresh)

    new_access = backend_app.create_access_token("user-rotation", jti="access-rotate-new")
    new_refresh = backend_app.create_refresh_token("user-rotation", jti="refresh-rotate-new")

    backend_app.revoked_tokens.add(old_payload["jti"])
    backend_app._store_session_token(new_access, "user-rotation")

    with pytest.raises(Exception):
        backend_app.decode_refresh_token(old_refresh)
    assert backend_app.is_token_revoked(old_payload["jti"]) is True
    assert backend_app.decode_access_token(new_access)["sub"] == "user-rotation"
    assert backend_app.decode_refresh_token(new_refresh)["sub"] == "user-rotation"


def test_google_login_creates_and_reuses_verified_account(monkeypatch):
    backend_app.sessions.clear()
    backend_app._init_auth_storage()
    google_sub = f"test-google-sub-{backend_app.uuid4().hex}"

    class FakeGoogleToken:
        @staticmethod
        def verify_oauth2_token(*_args, **_kwargs):
            return {"sub": google_sub, "email": f"{google_sub}@example.com", "email_verified": True}

    monkeypatch.setattr(backend_app, "GOOGLE_OAUTH_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(backend_app, "google_id_token", FakeGoogleToken)
    monkeypatch.setattr(backend_app, "google_requests", type("Requests", (), {"Request": staticmethod(lambda: object())}))

    first = backend_app.google_login(backend_app.GoogleCredential(credential="x" * 30))
    second = backend_app.google_login(backend_app.GoogleCredential(credential="x" * 30))

    assert first["username"] == f"{google_sub}@example.com"
    assert first["token"]
    assert second["token"]
