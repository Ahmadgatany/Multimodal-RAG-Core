import json
import logging
import time
from collections import OrderedDict
from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import Lock
from typing import Any, Optional
from fastapi import BackgroundTasks, FastAPI, Request, UploadFile, File, Form, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from io import BytesIO
from pydantic import BaseModel, Field
from pathlib import Path
import uvicorn
from PIL import Image
from uuid import uuid4
import hashlib
import secrets
import sqlite3

import jwt
from sqlalchemy import text

try:
    from .database import Base, SessionLocal, engine
    from .models import RefreshToken, RevokedToken, User
except ImportError:  # pragma: no cover
    Base = None
    engine = None
    SessionLocal = None
    RefreshToken = None
    RevokedToken = None
    User = None

try:
    import redis
except ImportError:  # pragma: no cover
    redis = None

try:
    from .config import (
        AGENT_CACHE_SIZE,
        ALLOWED_ORIGINS,
        ALLOWED_EXTENSIONS,
        AUTH_BACKEND,
        AUTH_DB_PATH,
        CHAT_HISTORY_DB_PATH,
        CHAT_HISTORY_RETENTION_DAYS,
        DATABASE_URL,
        GOOGLE_MODEL,
        JWT_ACCESS_TOKEN_TTL_SECONDS,
        JWT_ALGORITHM,
        JWT_REFRESH_TOKEN_TTL_SECONDS,
        JWT_SECRET_KEY,
        LLM_PROVIDER,
        MAX_ACTIVE_USERS,
        MAX_FILES_PER_USER,
        MAX_UPLOAD_MB,
        OPENROUTER_MODEL,
        PROVIDER_SETTINGS_DB_PATH,
        REDIS_URL,
        LOGIN_RATE_LIMIT,
        CHAT_RATE_LIMIT,
        UPLOAD_RATE_LIMIT,
        RATE_LIMIT_WINDOW_SECONDS,
        SESSION_TTL_SECONDS,
        SUPPORTED_PROVIDERS,
        UPLOAD_DIR,
        USE_VECTOR_DB,
        validate_runtime_configuration,
        get_provider_settings,
        get_runtime_provider_config,
        save_provider_settings,
    )
except ImportError:
    from config import (
        AGENT_CACHE_SIZE,
        ALLOWED_ORIGINS,
        ALLOWED_EXTENSIONS,
        AUTH_BACKEND,
        AUTH_DB_PATH,
        CHAT_HISTORY_DB_PATH,
        CHAT_HISTORY_RETENTION_DAYS,
        DATABASE_URL,
        GOOGLE_MODEL,
        JWT_ACCESS_TOKEN_TTL_SECONDS,
        JWT_ALGORITHM,
        JWT_REFRESH_TOKEN_TTL_SECONDS,
        JWT_SECRET_KEY,
        LLM_PROVIDER,
        MAX_ACTIVE_USERS,
        MAX_FILES_PER_USER,
        MAX_UPLOAD_MB,
        OPENROUTER_MODEL,
        PROVIDER_SETTINGS_DB_PATH,
        REDIS_URL,
        LOGIN_RATE_LIMIT,
        CHAT_RATE_LIMIT,
        UPLOAD_RATE_LIMIT,
        RATE_LIMIT_WINDOW_SECONDS,
        SESSION_TTL_SECONDS,
        SUPPORTED_PROVIDERS,
        UPLOAD_DIR,
        USE_VECTOR_DB,
        validate_runtime_configuration,
        get_provider_settings,
        get_runtime_provider_config,
        save_provider_settings,
    )

try:
    from .rag_core import LANGCHAIN_AVAILABLE, RAGCore
except ImportError:
    from rag_core import LANGCHAIN_AVAILABLE, RAGCore


# ---------------------------------------------
# ---------------- FastAPI App ----------------
# ---------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("multimodal_rag")

app = FastAPI(title="Multimodal RAG API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)
STORAGE_DIR = UPLOAD_DIR
PROVIDER_SETTINGS_DB_PATH = PROVIDER_SETTINGS_DB_PATH
agents: "OrderedDict[tuple[str, str], RAGCore]" = OrderedDict()
sessions: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
revoked_tokens: "set[str]" = set()
_rate_limit_events: dict[str, deque[float]] = defaultdict(deque)
_rate_limit_lock = Lock()
_metrics_lock = Lock()
_metrics: dict[str, Any] = {"requests": 0, "errors": 0, "response_ms_total": 0.0, "llm_requests": 0, "llm_by_provider": defaultdict(int)}

if REDIS_URL and redis is not None:
    try:
        redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
    except Exception:
        redis_client = None
else:
    redis_client = None


def _redis_key(prefix: str, value: str) -> str:
    return f"{prefix}:{value}"


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", uuid4().hex)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - started) * 1000
        with _metrics_lock:
            _metrics["requests"] += 1
            _metrics["errors"] += 1
            _metrics["response_ms_total"] += duration_ms
        logger.exception(json.dumps({"event": "request_failed", "request_id": request_id, "path": request.url.path, "method": request.method, "duration_ms": round(duration_ms, 1)}))
        raise
    duration_ms = (time.perf_counter() - started) * 1000
    with _metrics_lock:
        _metrics["requests"] += 1
        _metrics["response_ms_total"] += duration_ms
        _metrics["errors"] += int(response.status_code >= 500)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith(("/auth", "/settings", "/profile")) else "private"
    response.headers["X-Request-ID"] = request_id
    logger.info(json.dumps({"event": "request_completed", "request_id": request_id, "path": request.url.path, "method": request.method, "status": response.status_code, "duration_ms": round(duration_ms, 1)}))
    return response


def _enforce_rate_limit(scope: str, identifier: str, limit: int) -> None:
    key = f"rate:{scope}:{identifier}"
    if redis_client is not None:
        count = redis_client.incr(key)
        if count == 1:
            redis_client.expire(key, RATE_LIMIT_WINDOW_SECONDS)
        if count > limit:
            raise HTTPException(429, "Too many requests. Please try again shortly.")
        return
    now = time.time()
    with _rate_limit_lock:
        events = _rate_limit_events[key]
        while events and now - events[0] >= RATE_LIMIT_WINDOW_SECONDS:
            events.popleft()
        if len(events) >= limit:
            raise HTTPException(429, "Too many requests. Please try again shortly.")
        events.append(now)


def hash_token_value(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_access_token(user_id: str, expires_in: Optional[int] = None, jti: Optional[str] = None) -> str:
    now = int(time.time())
    token_ttl = int(expires_in if expires_in is not None else JWT_ACCESS_TOKEN_TTL_SECONDS)
    payload = {
        "sub": user_id,
        "type": "access",
        "iat": now,
        "exp": now + token_ttl,
        "jti": jti or uuid4().hex,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str, expires_in: Optional[int] = None, jti: Optional[str] = None) -> str:
    now = int(time.time())
    token_ttl = int(expires_in if expires_in is not None else JWT_REFRESH_TOKEN_TTL_SECONDS)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "iat": now,
        "exp": now + token_ttl,
        "jti": jti or uuid4().hex,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def is_token_revoked(token_or_jti: str) -> bool:
    value = token_or_jti
    if value.count(".") >= 2:
        try:
            payload = jwt.decode(token_or_jti, options={"verify_signature": False, "verify_exp": False})
            value = payload.get("jti")
        except Exception:
            return False
    if not value:
        return False
    if value in revoked_tokens:
        return True
    if redis_client is not None:
        return bool(redis_client.exists(_redis_key("revoked", value)))
    return False


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "exp", "jti"]})
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(401, "Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(401, "Invalid token") from exc

    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token type")

    if is_token_revoked(payload.get("jti", "")):
        raise HTTPException(401, "Token revoked")

    return payload


def decode_refresh_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM], options={"require": ["sub", "exp", "jti"]})
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(401, "Refresh token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(401, "Invalid refresh token") from exc

    if payload.get("type") != "refresh":
        raise HTTPException(401, "Invalid token type")

    if is_token_revoked(payload.get("jti", "")):
        raise HTTPException(401, "Refresh token revoked")

    return payload


def _reset_sqlalchemy_schema_if_needed() -> None:
    if Base is None or engine is None:
        return
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass


def _safe_db_session():
    if SessionLocal is None:
        return None
    try:
        _reset_sqlalchemy_schema_if_needed()
        return SessionLocal()
    except Exception:
        return None


def _store_revoked_jti(jti: str, user_id: Optional[str], token_type: str = "access", reason: Optional[str] = None):
    if RevokedToken is None:
        return
    db = _safe_db_session()
    if db is None:
        return
    try:
        existing = db.query(RevokedToken).filter_by(jti=jti).first()
        if existing:
            return
        db.add(
            RevokedToken(
                id=uuid4().hex,
                jti=jti,
                user_id=user_id,
                token_type=token_type,
                reason=reason,
                revoked_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(seconds=max(JWT_ACCESS_TOKEN_TTL_SECONDS, JWT_REFRESH_TOKEN_TTL_SECONDS)),
            )
        )
        db.commit()
    except Exception:
        pass
    finally:
        db.close()


def _store_refresh_token_record(user_id: str, refresh_token: str) -> None:
    if RefreshToken is None:
        return
    db = _safe_db_session()
    if db is None:
        return
    try:
        db.add(
            RefreshToken(
                id=uuid4().hex,
                user_id=user_id,
                token_hash=hash_token_value(refresh_token),
                expires_at=datetime.utcnow() + timedelta(seconds=JWT_REFRESH_TOKEN_TTL_SECONDS),
                revoked=False,
                created_at=datetime.utcnow(),
            )
        )
        db.commit()
    except Exception:
        pass
    finally:
        db.close()


def _revoke_refresh_token_record(refresh_token: str, reason: str = "logout") -> None:
    if RefreshToken is None:
        return
    db = _safe_db_session()
    if db is None:
        return
    try:
        token_hash = hash_token_value(refresh_token)
        row = db.query(RefreshToken).filter_by(token_hash=token_hash).first()
        if row is not None:
            row.revoked = True
            db.commit()
    except Exception:
        pass
    finally:
        db.close()


def logout_session_token(token: str) -> dict[str, str]:
    try:
        payload = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
    except Exception:
        payload = {}

    jti = payload.get("jti") or "unknown"
    user_id = payload.get("sub")
    if token in sessions:
        sessions.pop(token, None)
    if user_id:
        for session_token, record in list(sessions.items()):
            if record.get("user_id") == user_id:
                sessions.pop(session_token, None)
    revoked_tokens.add(jti)
    _store_revoked_jti(jti, user_id, token_type=payload.get("type", "access"), reason="logout")
    if payload.get("type") == "refresh":
        _revoke_refresh_token_record(token, reason="logout")
    if redis_client is not None:
        redis_client.setex(_redis_key("revoked", jti), JWT_ACCESS_TOKEN_TTL_SECONDS, "1")
        redis_client.delete(_redis_key("session", token))
    return {"message": "Logged out successfully"}


def _store_session_token(token: str, user_id: str) -> None:
    sessions[token] = {"user_id": user_id, "last_seen": time.time()}
    if redis_client is not None:
        redis_client.setex(_redis_key("session", token), SESSION_TTL_SECONDS, user_id)


def _clear_session_token(token: str) -> None:
    sessions.pop(token, None)
    if redis_client is not None:
        redis_client.delete(_redis_key("session", token))


def _init_chat_history_storage():
    CHAT_HISTORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(CHAT_HISTORY_DB_PATH) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS conversations ("
            "id TEXT PRIMARY KEY, user_id TEXT NOT NULL, title TEXT NOT NULL DEFAULT 'New chat', "
            "created_at REAL NOT NULL, updated_at REAL NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS messages ("
            "id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, "
            "content TEXT NOT NULL, created_at REAL NOT NULL, metadata TEXT DEFAULT '{}')"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_user_created ON messages(user_id, created_at)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, created_at)"
        )


def _prune_chat_history(now: Optional[float] = None):
    _init_chat_history_storage()
    current_time = time.time() if now is None else now
    cutoff = current_time - (CHAT_HISTORY_RETENTION_DAYS * 86400)
    with sqlite3.connect(CHAT_HISTORY_DB_PATH) as connection:
        connection.execute(
            "DELETE FROM messages WHERE created_at < ?",
            (cutoff,),
        )
        stale_conversations = connection.execute(
            "SELECT id FROM conversations WHERE updated_at < ?",
            (cutoff,),
        ).fetchall()
        if stale_conversations:
            placeholders = ", ".join("?" for _ in stale_conversations)
            connection.execute(f"DELETE FROM conversations WHERE id IN ({placeholders})", [row[0] for row in stale_conversations])


def _save_chat_message(user_id: str, role: str, content: str, conversation_id: Optional[str] = None, created_at: Optional[float] = None, title: Optional[str] = None):
    _init_chat_history_storage()
    current_time = float(created_at if created_at is not None else time.time())
    if conversation_id is None:
        conversation_id = uuid4().hex
        if title is None:
            title = content[:40].strip() or "New chat"
        with sqlite3.connect(CHAT_HISTORY_DB_PATH) as connection:
            connection.execute(
                "INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, user_id, title, current_time, current_time),
            )

    message_id = uuid4().hex
    with sqlite3.connect(CHAT_HISTORY_DB_PATH) as connection:
        connection.execute(
            "INSERT INTO messages (id, conversation_id, user_id, role, content, created_at, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (message_id, conversation_id, user_id, role, content, current_time, json.dumps({"title": title or "New chat"})),
        )
        connection.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (current_time, conversation_id),
        )
    return conversation_id


def _get_user_conversations(user_id: str):
    _init_chat_history_storage()
    with sqlite3.connect(CHAT_HISTORY_DB_PATH) as connection:
        rows = connection.execute(
            "SELECT id, title, created_at, updated_at FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [
        {
            "id": row[0],
            "title": row[1],
            "created_at": row[2],
            "updated_at": row[3],
        }
        for row in rows
    ]


def _get_conversation_messages(user_id: str, conversation_id: str):
    _init_chat_history_storage()
    with sqlite3.connect(CHAT_HISTORY_DB_PATH) as connection:
        rows = connection.execute(
            "SELECT role, content, created_at FROM messages WHERE user_id = ? AND conversation_id = ? ORDER BY created_at ASC",
            (user_id, conversation_id),
        ).fetchall()
    return [{"role": row[0], "content": row[1], "created_at": row[2]} for row in rows]


def _prune_sessions(now: Optional[float] = None):
    current_time = time.time() if now is None else now
    expired_tokens = [
        token
        for token, record in sessions.items()
        if current_time - float(record.get("last_seen", current_time)) > SESSION_TTL_SECONDS
    ]
    for token in expired_tokens:
        sessions.pop(token, None)

    while len(sessions) > MAX_ACTIVE_USERS:
        sessions.popitem(last=False)


def _evict_oldest_agent():
    if not agents:
        return
    agents.popitem(last=False)


def _touch_session(token: str) -> Optional[str]:
    record = sessions.get(token)
    if record is None:
        return None

    if time.time() - float(record.get("last_seen", time.time())) > SESSION_TTL_SECONDS:
        sessions.pop(token, None)
        return None

    record["last_seen"] = time.time()
    sessions.move_to_end(token)
    return record.get("user_id")


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    k: int = Field(default=5, ge=1, le=10)
    conversation_id: str = Field(min_length=1)


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=256)


class ProviderSettingsRequest(BaseModel):
    provider: str
    api_key: str = ""
    model_name: str = ""
    enabled: bool = True


def _init_auth_storage():
    _reset_sqlalchemy_schema_if_needed()
    # Local development used an older SQLite schema before Alembic was added.
    # Keep it upgradeable without compromising the PostgreSQL production path.
    if engine is not None and engine.dialect.name == "sqlite":
        with engine.begin() as connection:
            columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(users)")}
            if "created_at" not in columns:
                connection.exec_driver_sql("ALTER TABLE users ADD COLUMN created_at DATETIME")
            if "updated_at" not in columns:
                connection.exec_driver_sql("ALTER TABLE users ADD COLUMN updated_at DATETIME")


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        if stored.startswith("scrypt$"):
            _, salt_hex, digest_hex = stored.split("$", 2)
            candidate = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        else:  # Legacy PBKDF2 hashes remain valid and are upgraded after login.
            salt_hex, digest_hex = stored.split("$", 1)
            candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 120_000)
        return secrets.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _current_user(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")

    token = authorization[7:].strip()
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(401, "Invalid token payload")

    current_record = sessions.get(token)
    if current_record is None:
        _store_session_token(token, user_id)
    else:
        current_record["last_seen"] = time.time()
        sessions.move_to_end(token)

    return user_id


def _require_user(user_id: str) -> User:
    if SessionLocal is None or User is None:
        raise HTTPException(503, "Authentication database is unavailable")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            raise HTTPException(401, "User no longer exists")
        db.expunge(user)
        return user
    finally:
        db.close()


def _conversation_exists(user_id: str, conversation_id: str) -> bool:
    _init_chat_history_storage()
    with sqlite3.connect(CHAT_HISTORY_DB_PATH) as connection:
        return connection.execute(
            "SELECT 1 FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user_id),
        ).fetchone() is not None


def _get_agent(user_id: str, conversation_id: str) -> RAGCore:
    key = (user_id, conversation_id)
    if key in agents:
        agents.move_to_end(key)
        return agents[key]

    while len(agents) >= AGENT_CACHE_SIZE:
        _evict_oldest_agent()

    conversation_dir = STORAGE_DIR / user_id / "conversations" / conversation_id
    conversation_dir.mkdir(parents=True, exist_ok=True)
    (conversation_dir / "uploads").mkdir(parents=True, exist_ok=True)
    agent = RAGCore(
        upload_dir=str(conversation_dir / "uploads"),
        db_path=str(conversation_dir / "rag.sqlite3"),
        user_id=user_id,
    )
    agents[key] = agent
    agents.move_to_end(key)
    return agent

    while len(agents) >= AGENT_CACHE_SIZE:
        _evict_oldest_agent()

    user_dir = STORAGE_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "uploads").mkdir(parents=True, exist_ok=True)
    agent = RAGCore(upload_dir=str(user_dir / "uploads"), db_path=str(user_dir / "rag.sqlite3"), user_id=user_id)
    agents[user_id] = agent
    agents.move_to_end(user_id)
    return agent

@app.on_event("startup")
def startup_event():
    validate_runtime_configuration()
    _init_auth_storage()
    _init_chat_history_storage()
    _reset_sqlalchemy_schema_if_needed()
    get_provider_settings()


@app.post("/auth/register")
def register(credentials: Credentials, request: Request = None):
    _enforce_rate_limit("register", request.client.host if request and request.client else "unknown", LOGIN_RATE_LIMIT)
    username = credentials.username.strip()
    if len(username) < 3 or len(credentials.password) < 6:
        raise HTTPException(400, "Username must have 3 characters and password 6 characters")
    if SessionLocal is None or User is None:
        raise HTTPException(503, "Authentication database is unavailable")
    db = SessionLocal()
    try:
        if db.query(User).filter(User.username == username).first():
            raise HTTPException(409, "Username already exists")
        db.add(User(id=uuid4().hex, username=username, password_hash=_hash_password(credentials.password)))
        db.commit()
    finally:
        db.close()
    return {"message": "Account created"}


@app.post("/auth/login")
def login(credentials: Credentials, request: Request = None):
    _enforce_rate_limit("login", f"{request.client.host if request and request.client else 'unknown'}:{credentials.username.strip().lower()}", LOGIN_RATE_LIMIT)
    if User is not None and SessionLocal is not None:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == credentials.username.strip()).first()
            if not user or not _verify_password(credentials.password, user.password_hash):
                raise HTTPException(401, "Invalid username or password")
            if not user.password_hash.startswith("scrypt$"):
                user.password_hash = _hash_password(credentials.password)
                db.commit()
        finally:
            db.close()

        _prune_sessions()
        if len(sessions) >= MAX_ACTIVE_USERS:
            raise HTTPException(429, f"Maximum active users reached ({MAX_ACTIVE_USERS}). Please retry in a moment.")
        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token(user.id)
        _store_session_token(access_token, user.id)
        _store_refresh_token_record(user.id, refresh_token)
        _prune_chat_history()
        return {
            "token": access_token,
            "refresh_token": refresh_token,
            "username": user.username,
            "expires_in": JWT_ACCESS_TOKEN_TTL_SECONDS,
            "refresh_expires_in": JWT_REFRESH_TOKEN_TTL_SECONDS,
        }

    with sqlite3.connect(AUTH_DB_PATH) as connection:
        user = connection.execute(
            "SELECT id, password_hash FROM users WHERE username = ?", (credentials.username.strip(),)
        ).fetchone()
    if not user or not _verify_password(credentials.password, user[1]):
        raise HTTPException(401, "Invalid username or password")

    _prune_sessions()
    if len(sessions) >= MAX_ACTIVE_USERS:
        raise HTTPException(429, f"Maximum active users reached ({MAX_ACTIVE_USERS}). Please retry in a moment.")

    token = create_access_token(user[0])
    refresh_token = create_refresh_token(user[0])
    _store_session_token(token, user[0])
    _store_refresh_token_record(user[0], refresh_token)
    _prune_chat_history()
    return {
        "token": token,
        "refresh_token": refresh_token,
        "username": credentials.username.strip(),
        "expires_in": JWT_ACCESS_TOKEN_TTL_SECONDS,
        "refresh_expires_in": JWT_REFRESH_TOKEN_TTL_SECONDS,
    }


@app.post("/auth/refresh")
def refresh_token(payload: dict[str, str]):
    refresh_token_value = (payload.get("refresh_token") or "").strip()
    if not refresh_token_value:
        raise HTTPException(400, "Refresh token is required")

    decoded = decode_refresh_token(refresh_token_value)
    user_id = decoded.get("sub")
    if not user_id:
        raise HTTPException(401, "Invalid refresh token")

    if RefreshToken is not None:
        db = SessionLocal()
        try:
            existing = db.query(RefreshToken).filter_by(token_hash=hash_token_value(refresh_token_value), revoked=False).first()
            if not existing or existing.expires_at <= datetime.utcnow():
                raise HTTPException(401, "Refresh token expired or revoked")
            existing.revoked = True
            db.commit()
        finally:
            db.close()

    new_access = create_access_token(user_id)
    new_refresh = create_refresh_token(user_id)
    _store_session_token(new_access, user_id)
    _store_refresh_token_record(user_id, new_refresh)
    return {
        "token": new_access,
        "refresh_token": new_refresh,
        "expires_in": JWT_ACCESS_TOKEN_TTL_SECONDS,
        "refresh_expires_in": JWT_REFRESH_TOKEN_TTL_SECONDS,
    }


@app.get("/settings/providers")
def get_provider_settings_route(authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    return {"providers": get_provider_settings(user_id), "supported": SUPPORTED_PROVIDERS, "active": LLM_PROVIDER}


@app.post("/settings/providers")
def save_provider_settings_route(payload: ProviderSettingsRequest, authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    provider_name = payload.provider.strip().lower()
    if provider_name not in SUPPORTED_PROVIDERS or provider_name not in {"google", "openrouter"}:
        raise HTTPException(400, "Unsupported provider")
    if not payload.model_name.strip():
        raise HTTPException(400, "model_name is required")
    save_provider_settings(user_id, provider_name, payload.api_key.strip(), payload.model_name.strip(), payload.enabled)
    return {"provider": provider_name, "saved": True, "configured": get_provider_settings(user_id)[provider_name]["configured"]}


@app.post("/auth/logout")
def logout(authorization: Optional[str] = Header(None), refresh_token: Optional[str] = None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Authentication required")
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(401, "Authentication required")

    if refresh_token:
        try:
            payload = decode_refresh_token(refresh_token)
            if payload.get("sub"):
                _store_revoked_jti(payload.get("jti", ""), payload.get("sub"), token_type="refresh", reason="logout")
                _revoke_refresh_token_record(refresh_token, reason="logout")
        except HTTPException:
            pass

    return logout_session_token(token)


@app.get("/profile")
def get_profile(authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    user = _require_user(user_id)

    return {
        "user_id": user_id,
        "username": user.username,
        "supported_providers": SUPPORTED_PROVIDERS,
    }


@app.get("/chat/history")
def chat_history(authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    return {"conversations": _get_user_conversations(user_id)}


@app.get("/chat/history/{conversation_id}")
def chat_history_detail(conversation_id: str, authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    if not _conversation_exists(user_id, conversation_id):
        raise HTTPException(404, "Conversation not found")
    return {"conversation_id": conversation_id, "messages": _get_conversation_messages(user_id, conversation_id)}


@app.delete("/chat/history/{conversation_id}")
def delete_conversation(conversation_id: str, authorization: Optional[str] = Header(None)):
    """Delete a conversation and all its messages."""
    user_id = _current_user(authorization)
    _init_chat_history_storage()
    
    try:
        with sqlite3.connect(CHAT_HISTORY_DB_PATH) as connection:
            # Verify user owns this conversation
            conv = connection.execute(
                "SELECT user_id FROM conversations WHERE id = ?",
                (conversation_id,),
            ).fetchone()
            
            if not conv or conv[0] != user_id:
                raise HTTPException(403, "Unauthorized to delete this conversation")
            
            # Delete messages
            connection.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
            # Delete conversation
            connection.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,),
            )
            connection.commit()
        
        return {"status": "deleted", "conversation_id": conversation_id}
    except Exception as error:
        raise HTTPException(500, "Failed to delete conversation") from error


@app.post("/chat/save")
def save_chat_message(data: dict[str, Any], authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    _enforce_rate_limit("chat_save", user_id, CHAT_RATE_LIMIT * 2)
    conversation_id = data.get("conversation_id")
    role = data.get("role", "user")
    content = str(data.get("content") or "")
    title = data.get("title")
    created_at = data.get("created_at")
    if role not in {"user", "assistant"}:
        raise HTTPException(422, "role must be user or assistant")
    if not content or len(content) > 12000:
        raise HTTPException(400, "content must be between 1 and 12000 characters")
    if conversation_id is not None and not _conversation_exists(user_id, str(conversation_id)):
        raise HTTPException(404, "Conversation not found")
    return {"conversation_id": _save_chat_message(user_id, role, content, conversation_id, created_at, title)}


@app.get("/")
def root():
    return {
        "status": "ok",
        "provider": LLM_PROVIDER,
        "model": GOOGLE_MODEL if LLM_PROVIDER == "google" else OPENROUTER_MODEL if LLM_PROVIDER == "openrouter" else "huggingface",
        "vector_db_enabled": USE_VECTOR_DB
    }

def _ingest_file(user_id: str, conversation_id: str, document_id: str, path: str) -> None:
    agent = _get_agent(user_id, conversation_id)
    job = agent.get_job(document_id)
    agent.ingest_file(document_id, path, display_name=job.get("filename") if job else None)


@app.get("/health")
def health():
    """Liveness probe: the process is able to serve HTTP requests."""
    return {"status": "ok"}


@app.get("/ready")
def readiness():
    """Readiness probe: required persistence services are reachable."""
    checks = {"database": False, "redis": not bool(REDIS_URL)}
    try:
        if SessionLocal is not None:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
        else:
            with sqlite3.connect(AUTH_DB_PATH) as connection:
                connection.execute("SELECT 1")
        checks["database"] = True
    except Exception:
        pass
    try:
        checks["redis"] = redis_client is not None and bool(redis_client.ping())
    except Exception:
        pass
    if not all(checks.values()):
        raise HTTPException(503, {"status": "not_ready", "checks": checks})
    return {"status": "ready", "checks": checks}


@app.get("/metrics")
def metrics(authorization: Optional[str] = Header(None)):
    """Authenticated operational summary; values intentionally exclude secrets."""
    _current_user(authorization)
    with _metrics_lock:
        snapshot = dict(_metrics)
    request_count = snapshot["requests"]
    return {
        "requests": request_count,
        "errors": snapshot["errors"],
        "average_response_ms": round(snapshot["response_ms_total"] / request_count, 1) if request_count else 0,
        "llm_requests": snapshot["llm_requests"],
        "llm_by_provider": dict(snapshot["llm_by_provider"]),
        "active_cached_users": len(agents),
        "uploaded_documents": sum(len(agent.list_jobs()) for agent in agents.values()),
    }


@app.get("/documents")
def list_documents(conversation_id: str = Query(...), authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    if not _conversation_exists(user_id, conversation_id):
        raise HTTPException(404, "Conversation not found")
    return {"documents": _get_agent(user_id, conversation_id).list_jobs()}


@app.get("/documents/{document_id}")
def get_document(document_id: str, conversation_id: str = Query(...), authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    if not _conversation_exists(user_id, conversation_id):
        raise HTTPException(404, "Conversation not found")
    job = _get_agent(user_id, conversation_id).get_job(document_id)
    if job is None:
        raise HTTPException(404, "Document not found")
    return job


@app.get("/documents/{document_id}/pages/{page_number}")
def get_document_page(document_id: str, page_number: int, conversation_id: str = Query(...), authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    if not _conversation_exists(user_id, conversation_id):
        raise HTTPException(404, "Conversation not found")
    page = _get_agent(user_id, conversation_id).get_document_page(document_id, page_number)
    if page is None:
        raise HTTPException(404, "Document page not found")
    return page


@app.post("/upload_file", status_code=status.HTTP_202_ACCEPTED)
async def upload_file(background_tasks: BackgroundTasks, conversation_id: str = Form(...), file: UploadFile = File(...), authorization: Optional[str] = Header(None)):
    """Accept PDF or image uploads. Extract text and add to agent's docs.
    Returns path and a short message. Multiple uploads can be sent in sequence.
    """
    user_id = _current_user(authorization)
    if not _conversation_exists(user_id, conversation_id):
        raise HTTPException(404, "Conversation not found")
    _enforce_rate_limit("upload", user_id, UPLOAD_RATE_LIMIT)
    agent = _get_agent(user_id, conversation_id)

    # save file
    filename = Path(file.filename or "upload").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "Unsupported file type")
    content_type = (file.content_type or "").lower()
    expected_types = {
        ".pdf": {"application/pdf"},
        ".txt": {"text/plain"}, ".md": {"text/markdown", "text/plain"},
        ".png": {"image/png"}, ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"},
        ".gif": {"image/gif"}, ".bmp": {"image/bmp"}, ".tiff": {"image/tiff"},
    }
    if content_type and content_type != "application/octet-stream" and content_type not in expected_types[suffix]:
        raise HTTPException(415, "File content type does not match its extension")
    if len(agent.list_jobs()) >= MAX_FILES_PER_USER:
        raise HTTPException(429, f"Maximum document limit reached ({MAX_FILES_PER_USER})")

    out_path = agent.upload_dir / f"{uuid4().hex}{suffix}"
    try:
        content = await file.read()
        if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"File exceeds the {MAX_UPLOAD_MB} MB limit")
        if not content:
            raise HTTPException(400, "Uploaded file is empty")
        if suffix == ".pdf" and not content.startswith(b"%PDF-"):
            raise HTTPException(415, "Invalid PDF file")
        if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"}:
            try:
                probe = Image.open(BytesIO(content))
                probe.verify()
            except Exception as error:
                raise HTTPException(415, "Invalid image file") from error
        out_path.write_bytes(content)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(500, "Failed to save uploaded file") from error

    document_id = agent.create_ingestion_job(filename)
    background_tasks.add_task(_ingest_file, user_id, conversation_id, document_id, str(out_path))
    return {"message": "File uploaded and processing will start shortly.", "document_id": document_id, "status": "uploaded"}

@app.post("/chat")
def chat(request: QueryRequest, authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    if not _conversation_exists(user_id, request.conversation_id):
        raise HTTPException(404, "Conversation not found")
    _enforce_rate_limit("chat", user_id, CHAT_RATE_LIMIT)
    agent = _get_agent(user_id, request.conversation_id)

    try:
        with _metrics_lock:
            _metrics["llm_requests"] += 1
            _metrics["llm_by_provider"][LLM_PROVIDER] += 1
        return agent.answer_with_sources(request.question, k=request.k)
    except Exception as error:
        logger.exception(json.dumps({"event": "chat_model_failed", "user_id": user_id, "error_type": type(error).__name__}))
        raise HTTPException(502, "The model request failed") from error


@app.post("/chat_with_image")
async def chat_with_image(
    question: str = Form(...),
    conversation_id: str = Form(...),
    image: Optional[UploadFile] = File(None), 
    k: Optional[int] = Form(5),
    authorization: Optional[str] = Header(None)
):
    user_id = _current_user(authorization)
    if not _conversation_exists(user_id, conversation_id):
        raise HTTPException(404, "Conversation not found")
    _enforce_rate_limit("chat_image", user_id, CHAT_RATE_LIMIT)
    if not question.strip() or len(question) > 4000:
        raise HTTPException(422, "question must be between 1 and 4000 characters")
    agent = _get_agent(user_id, conversation_id)
    
    img_data = None
    if image is not None:
        try:
            img_stream = BytesIO(await image.read())
            img_data = Image.open(img_stream)
        except Exception as error:
            raise HTTPException(415, "Failed to process image") from error

    try:
        with _metrics_lock:
            _metrics["llm_requests"] += 1
            _metrics["llm_by_provider"][LLM_PROVIDER] += 1
        return agent.answer_with_sources(question, image=img_data, k=k or 5)
    except Exception as error:
        logger.exception(json.dumps({"event": "image_chat_model_failed", "user_id": user_id, "error_type": type(error).__name__}))
        raise HTTPException(502, "The model request failed") from error

@app.post("/summarize")
def summarize(conversation_id: str = Query(...), authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    if not _conversation_exists(user_id, conversation_id):
        raise HTTPException(404, "Conversation not found")
    _enforce_rate_limit("summarize", user_id, max(1, CHAT_RATE_LIMIT // 3))
    agent = _get_agent(user_id, conversation_id)

    try:
        summaries = agent.summarize_all()
        return {"summaries": summaries}
    except Exception as error:
        raise HTTPException(502, "The model request failed") from error


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
