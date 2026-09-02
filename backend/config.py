import os
import sqlite3
import base64
import hashlib
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
load_dotenv(BASE_DIR / ".env")


def env_path(name: str, default: Path) -> Path:
    value = Path(os.getenv(name, str(default)))
    return (value if value.is_absolute() else BASE_DIR / value).resolve()

APP_ENV = os.getenv("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV in {"production", "prod"}
DATA_DIR = env_path("DATA_DIR", PROJECT_DIR / "data")
AUTH_DB_PATH = env_path("AUTH_DB_PATH", DATA_DIR / "users.sqlite3")
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{AUTH_DB_PATH}").strip()
REDIS_URL = os.getenv("REDIS_URL", "").strip()
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production-strong-secret-key-32+").strip()
PROVIDER_ENCRYPTION_KEY = os.getenv("PROVIDER_ENCRYPTION_KEY", "").strip()
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256").strip()
JWT_ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("JWT_ACCESS_TOKEN_TTL_SECONDS", "3600"))
JWT_REFRESH_TOKEN_TTL_SECONDS = int(os.getenv("JWT_REFRESH_TOKEN_TTL_SECONDS", "604800"))
AUTH_BACKEND = os.getenv("AUTH_BACKEND", "jwt").strip().lower()


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


UPLOAD_DIR = env_path("UPLOAD_DIR", DATA_DIR / "uploads")
DB_PATH = env_path("DB_PATH", DATA_DIR / "rag.sqlite3")
CHAT_HISTORY_DB_PATH = env_path("CHAT_HISTORY_DB_PATH", DATA_DIR / "chat_history.sqlite3")
PROVIDER_SETTINGS_DB_PATH = env_path("PROVIDER_SETTINGS_DB_PATH", DATA_DIR / "provider_settings.sqlite3")
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
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local").strip().lower()
USE_VECTOR_DB = env_bool("USE_VECTOR_DB", True)
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))
MAX_ACTIVE_USERS = int(os.getenv("MAX_ACTIVE_USERS", "30"))
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "1800"))
AGENT_CACHE_SIZE = int(os.getenv("AGENT_CACHE_SIZE", str(MAX_ACTIVE_USERS)))
CHAT_HISTORY_RETENTION_DAYS = int(os.getenv("CHAT_HISTORY_RETENTION_DAYS", "30"))
MAX_FILES_PER_USER = int(os.getenv("MAX_FILES_PER_USER", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
LOGIN_RATE_LIMIT = int(os.getenv("LOGIN_RATE_LIMIT", "10"))
CHAT_RATE_LIMIT = int(os.getenv("CHAT_RATE_LIMIT", "30"))
UPLOAD_RATE_LIMIT = int(os.getenv("UPLOAD_RATE_LIMIT", "10"))
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv("ALLOWED_ORIGINS", "http://localhost:8501").split(",") if origin.strip()]
SUPPORTED_PROVIDERS = [
    provider.strip().lower()
    for provider in os.getenv("SUPPORTED_PROVIDERS", "google,openrouter,groq").split(",")
    if provider.strip()
]
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"}


def validate_runtime_configuration() -> None:
    """Fail fast for unsafe production configuration instead of serving insecurely."""
    if not IS_PRODUCTION:
        return
    if DATABASE_URL.startswith("sqlite"):
        raise RuntimeError("DATABASE_URL must point to PostgreSQL in production")
    if JWT_SECRET_KEY == "change-me-in-production-strong-secret-key-32+" or len(JWT_SECRET_KEY) < 32:
        raise RuntimeError("JWT_SECRET_KEY must be a unique secret of at least 32 characters in production")
    if not PROVIDER_ENCRYPTION_KEY:
        raise RuntimeError("PROVIDER_ENCRYPTION_KEY is required in production")
    if not REDIS_URL:
        raise RuntimeError("REDIS_URL is required in production")
    if "*" in ALLOWED_ORIGINS:
        raise RuntimeError("ALLOWED_ORIGINS cannot contain '*' in production")


def _init_provider_settings_db():
    PROVIDER_SETTINGS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(PROVIDER_SETTINGS_DB_PATH) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS user_provider_settings ("
            "user_id TEXT NOT NULL, provider TEXT NOT NULL, api_key_encrypted TEXT, "
            "model_name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, "
            "updated_at REAL NOT NULL DEFAULT (strftime('%s','now')), "
            "PRIMARY KEY (user_id, provider))"
        )
        # The previous global table stored plaintext keys and had no ownership model.
        # It cannot be migrated safely to a user, so remove it on first secure startup.
        legacy = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='provider_settings'").fetchone()
        if legacy:
            conn.execute("DROP TABLE provider_settings")


def _cipher() -> Fernet:
    if PROVIDER_ENCRYPTION_KEY:
        return Fernet(PROVIDER_ENCRYPTION_KEY.encode("ascii"))
    key_material = hashlib.sha256(JWT_SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key_material))


def _provider_defaults() -> dict[str, dict[str, object]]:
    return {
        "google": {"model_name": GOOGLE_MODEL, "enabled": True, "api_key": GOOGLE_API_KEY or ""},
        "openrouter": {"model_name": OPENROUTER_MODEL, "enabled": True, "api_key": OPENROUTER_API_KEY or ""},
        "groq": {"model_name": "llama-3.1-8b-instant", "enabled": False, "api_key": ""},
    }


def get_provider_settings(user_id: str | None = None) -> dict[str, dict[str, object]]:
    _init_provider_settings_db()
    defaults = _provider_defaults()
    if user_id is None:
        return {
            name: {"model_name": data["model_name"], "enabled": data["enabled"], "configured": bool(data["api_key"])}
            for name, data in defaults.items()
        }
    with sqlite3.connect(PROVIDER_SETTINGS_DB_PATH) as conn:
        rows = conn.execute(
            "SELECT provider, api_key_encrypted, model_name, enabled FROM user_provider_settings WHERE user_id=?", (user_id,)
        ).fetchall()
    settings = {name: {"model_name": data["model_name"], "enabled": data["enabled"], "configured": bool(data["api_key"])} for name, data in defaults.items()}
    for provider, encrypted_key, model_name, enabled in rows:
        settings[provider] = {"model_name": model_name, "enabled": bool(enabled), "configured": bool(encrypted_key)}
    return settings


def save_provider_settings(user_id: str, provider: str, api_key: str, model_name: str, enabled: bool) -> None:
    _init_provider_settings_db()
    encrypted_key = _cipher().encrypt(api_key.encode("utf-8")).decode("ascii") if api_key else None
    with sqlite3.connect(PROVIDER_SETTINGS_DB_PATH) as conn:
        existing = conn.execute("SELECT api_key_encrypted FROM user_provider_settings WHERE user_id=? AND provider=?", (user_id, provider)).fetchone()
        if encrypted_key is None and existing:
            encrypted_key = existing[0]
        conn.execute(
            "INSERT INTO user_provider_settings (user_id, provider, api_key_encrypted, model_name, enabled, updated_at) VALUES (?, ?, ?, ?, ?, strftime('%s','now')) "
            "ON CONFLICT(user_id, provider) DO UPDATE SET api_key_encrypted=excluded.api_key_encrypted, model_name=excluded.model_name, enabled=excluded.enabled, updated_at=excluded.updated_at",
            (user_id, provider, encrypted_key, model_name, int(enabled)),
        )


def get_runtime_provider_config(user_id: str | None = None):
    _init_provider_settings_db()
    provider_name = LLM_PROVIDER
    selected: dict[str, object] = {}
    if user_id:
        with sqlite3.connect(PROVIDER_SETTINGS_DB_PATH) as conn:
            row = conn.execute("SELECT api_key_encrypted, model_name, enabled FROM user_provider_settings WHERE user_id=? AND provider=?", (user_id, provider_name)).fetchone()
        if row:
            try:
                api_key = _cipher().decrypt(row[0].encode("ascii")).decode("utf-8") if row[0] else ""
            except InvalidToken as error:
                raise RuntimeError("Stored provider credential cannot be decrypted") from error
            selected = {"api_key": api_key, "model_name": row[1], "enabled": bool(row[2])}
    if selected and not selected.get("enabled"):
        raise RuntimeError(f"Provider '{provider_name}' is disabled for this user")
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
