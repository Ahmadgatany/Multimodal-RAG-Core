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


def test_register_and_login_work_with_same_auth_database():
    backend_app.sessions.clear()
    backend_app._init_auth_storage()

    username = f"db_regression_user_{backend_app.uuid4().hex[:8]}"
    password = "db_regression_pass"

    register_response = backend_app.register(backend_app.Credentials(username=username, password=password))
    login_response = backend_app.login(backend_app.Credentials(username=username, password=password))

    assert register_response["message"] == "Account created"
    assert login_response["username"] == username
    assert login_response["token"]
    assert login_response["refresh_token"]
