import os
import sqlite3
import time

from backend import app as backend_app


def test_chat_history_is_pruned_after_retention_window():
    backend_app.CHAT_HISTORY_DB_PATH = backend_app.STORAGE_DIR.parent / "test_chat_history.sqlite3"
    if os.path.exists(backend_app.CHAT_HISTORY_DB_PATH):
        os.remove(backend_app.CHAT_HISTORY_DB_PATH)

    backend_app._init_chat_history_storage()
    user_id = "user-123"
    conversation_id = backend_app._save_chat_message(
        user_id=user_id,
        role="user",
        content="hello",
        conversation_id=None,
        created_at=time.time() - (backend_app.CHAT_HISTORY_RETENTION_DAYS * 86400 + 10),
    )

    backend_app._prune_chat_history(now=time.time())
    with sqlite3.connect(backend_app.CHAT_HISTORY_DB_PATH) as connection:
        rows = connection.execute("SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,)).fetchone()[0]

    assert rows == 0


def test_first_user_message_names_existing_new_chat(tmp_path):
    backend_app.CHAT_HISTORY_DB_PATH = tmp_path / "chat_history.sqlite3"

    conversation_id = backend_app._create_conversation("user-123")
    backend_app._save_chat_message(
        user_id="user-123",
        role="user",
        content="How does retrieval work?",
        conversation_id=conversation_id,
        title="How does",
    )

    with sqlite3.connect(backend_app.CHAT_HISTORY_DB_PATH) as connection:
        title = connection.execute(
            "SELECT title FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()[0]

    assert title == "How does"
