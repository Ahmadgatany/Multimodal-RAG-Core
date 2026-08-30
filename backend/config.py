import os
import sqlite3
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'app.db'}").strip()
REDIS_URL = os.getenv("REDIS_URL", "").strip()
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production-strong-secret-key-32+").strip()
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256").strip()
JWT_ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("JWT_ACCESS_TOKEN_TTL_SECONDS", "3600"))
JWT_REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("JWT_REFRESH_TOKEN_TTL_SECONDS", "604800"))
AUTH_BACKEND = os.getenv("AUTH_BACKEND", "jwt").strip().lower()


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(BASE_DIR / "data" / "uploads")))
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "rag.sqlite3")))
CHAT_HISTORY_DB_PATH = Path(os.getenv("CHAT_HISTORY_DB_PATH", str(BASE_DIR / "data" / "chat_history.sqlite3")))
PROVIDER_SETTINGS_DB_PATH = Path(os.getenv("PROVIDER_SETTINGS_DB_PATH", str(BASE_DIR / "data" / "provider_settings.sqlite3")))
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "google").strip().lower()
GOOGLE_MODEL = os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "minimax/minimax-m3:free")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "http://localhost:8000")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "Multimodal RAG Core")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)
USE_VECTOR_DB = env_bool("USE_VECTOR_DB", True)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
MAX_ACTIVE_USERS = int(os.getenv("MAX_ACTIVE_USERS", "30"))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
AGENT_CACHE_SIZE = int(os.getenv("AGENT_CACHE_SIZE", str(MAX_ACTIVE_USERS)))
CHAT_HISTORY_RETENTION_DAYS = int(os.getenv("CHAT_HISTORY_RETENTION_DAYS", "30"))
SUPPORTED_PROVIDERS = [
    provider.strip().lower()
    for provider in os.getenv("SUPPORTED_PROVIDERS", "google,openrouter,groq").split(",")
    if provider.strip()
]
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"}


def _init_provider_settings_db():
    PROVIDER_SETTINGS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(PROVIDER_SETTINGS_DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS provider_settings ("
            "provider TEXT PRIMARY KEY, "
            "api_key TEXT, "
            "model_name TEXT, "
            "enabled INTEGER NOT NULL DEFAULT 1, "
            "updated_at REAL NOT NULL DEFAULT (strftime('%s','now'))"
            ")"
        )
        default_rows = [
            ("google", GOOGLE_API_KEY or "", GOOGLE_MODEL or "gemini-2.5-flash", 1),
            ("openrouter", OPENROUTER_API_KEY or "", OPENROUTER_MODEL or "minimax/minimax-m3:free", 1),
            ("groq", "", "llama-3.1-8b-instant", 0),
        ]
        for provider, api_key, model_name, enabled in default_rows:
            conn.execute(
                "INSERT OR IGNORE INTO provider_settings (provider, api_key, model_name, enabled) VALUES (?, ?, ?, ?)",
                (provider, api_key, model_name, int(enabled)),
            )


def get_provider_settings():
    _init_provider_settings_db()
    with sqlite3.connect(PROVIDER_SETTINGS_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT provider, api_key, model_name, enabled FROM provider_settings ORDER BY provider"
        ).fetchall()
    return {
        row[0]: {
            "api_key": row[1] or "",
            "model_name": row[2] or "",
            "enabled": bool(row[3]),
        }
        for row in rows
    }


def get_runtime_provider_config():
    settings = get_provider_settings()
    provider_name = LLM_PROVIDER
    selected = settings.get(provider_name, {})
    if provider_name == "google":
        return {
            "provider": "google",
            "api_key": selected.get("api_key") or GOOGLE_API_KEY or "",
            "model": selected.get("model_name") or GOOGLE_MODEL,
        }
    if provider_name == "openrouter":
        return {
            "provider": "openrouter",
            "api_key": selected.get("api_key") or OPENROUTER_API_KEY or "",
            "model": selected.get("model_name") or OPENROUTER_MODEL,
            "site_url": OPENROUTER_SITE_URL,
            "app_name": OPENROUTER_APP_NAME,
        }
    return {"provider": provider_name, "api_key": selected.get("api_key") or "", "model": selected.get("model_name") or GOOGLE_MODEL}
