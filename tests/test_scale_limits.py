import time

from backend import app as backend_app


def test_session_prune_keeps_only_active_limit():
    backend_app.sessions.clear()
    backend_app.agents.clear()
    now = time.time()

    for index in range(backend_app.MAX_ACTIVE_USERS):
        backend_app.sessions[f"token-{index}"] = {
            "user_id": f"user-{index}",
            "last_seen": now,
        }

    backend_app.sessions["token-overflow"] = {
        "user_id": "user-overflow",
        "last_seen": now,
    }

    backend_app._prune_sessions(now=now)

    assert len(backend_app.sessions) == backend_app.MAX_ACTIVE_USERS
    assert "token-0" not in backend_app.sessions
    assert "token-overflow" in backend_app.sessions


def test_agent_cache_evicts_oldest_entry():
    backend_app.agents.clear()
    for index in range(backend_app.AGENT_CACHE_SIZE):
        backend_app.agents[f"user-{index}"] = object()

    backend_app.agents["user-extra"] = object()
    backend_app._evict_oldest_agent()

    assert len(backend_app.agents) == backend_app.AGENT_CACHE_SIZE
    assert "user-0" not in backend_app.agents
    assert "user-extra" in backend_app.agents


def test_agents_are_isolated_by_conversation(tmp_path, monkeypatch):
    monkeypatch.setattr(backend_app, "STORAGE_DIR", tmp_path / "uploads")
    monkeypatch.setattr(backend_app, "CHAT_HISTORY_DB_PATH", tmp_path / "chat.sqlite3")
    backend_app.agents.clear()
    backend_app._init_chat_history_storage()

    first = backend_app._save_chat_message("user-123", "user", "first", title="First")
    second = backend_app._save_chat_message("user-123", "user", "second", title="Second")
    first_agent = backend_app._get_agent("user-123", first)
    second_agent = backend_app._get_agent("user-123", second)

    assert first_agent is not second_agent
    assert first_agent.db_path != second_agent.db_path
    assert first_agent.upload_dir != second_agent.upload_dir
