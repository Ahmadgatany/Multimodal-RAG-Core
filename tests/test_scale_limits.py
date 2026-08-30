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
