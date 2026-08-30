import json
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import Any, Optional
from fastapi import FastAPI, UploadFile, File, Form, Header, HTTPException
from io import BytesIO
from pydantic import BaseModel
from pathlib import Path
import uvicorn
from PIL import Image
from uuid import uuid4
import hashlib
import secrets
import sqlite3

import jwt

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
        ALLOWED_EXTENSIONS,
        AUTH_BACKEND,
        CHAT_HISTORY_DB_PATH,
        CHAT_HISTORY_RETENTION_DAYS,
        DATABASE_URL,
        GOOGLE_MODEL,
        JWT_ACCESS_TOKEN_TTL_SECONDS,
        JWT_ALGORITHM,
        JWT_SECRET_KEY,
        LLM_PROVIDER,
        MAX_ACTIVE_USERS,
        MAX_UPLOAD_MB,
        OPENROUTER_MODEL,
        PROVIDER_SETTINGS_DB_PATH,
        REDIS_URL,
        SESSION_TTL_SECONDS,
        SUPPORTED_PROVIDERS,
        UPLOAD_DIR,
        USE_VECTOR_DB,
        get_provider_settings,
        get_runtime_provider_config,
    )
except ImportError:
    from config import (
        AGENT_CACHE_SIZE,
        ALLOWED_EXTENSIONS,
        AUTH_BACKEND,
        CHAT_HISTORY_DB_PATH,
        CHAT_HISTORY_RETENTION_DAYS,
        DATABASE_URL,
        GOOGLE_MODEL,
        JWT_ACCESS_TOKEN_TTL_SECONDS,
        JWT_ALGORITHM,
        JWT_SECRET_KEY,
        LLM_PROVIDER,
        MAX_ACTIVE_USERS,
        MAX_UPLOAD_MB,
        OPENROUTER_MODEL,
        PROVIDER_SETTINGS_DB_PATH,
        REDIS_URL,
        SESSION_TTL_SECONDS,
        SUPPORTED_PROVIDERS,
        UPLOAD_DIR,
        USE_VECTOR_DB,
        get_provider_settings,
        get_runtime_provider_config,
    )

try:
    from .rag_core import LANGCHAIN_AVAILABLE, RAGCore
except ImportError:
    from rag_core import LANGCHAIN_AVAILABLE, RAGCore


# ---------------------------------------------
# ---------------- FastAPI App ----------------
# ---------------------------------------------

app = FastAPI(title="Multimodal RAG API", version="1.0.0")
STORAGE_DIR = UPLOAD_DIR
AUTH_DB_PATH = STORAGE_DIR.parent / "users.sqlite3"
CHAT_HISTORY_DB_PATH = CHAT_HISTORY_DB_PATH
PROVIDER_SETTINGS_DB_PATH = PROVIDER_SETTINGS_DB_PATH
agents: "OrderedDict[str, RAGCore]" = OrderedDict()
sessions: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
revoked_tokens: "set[str]" = set()

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
    question: str
    k: int = 5


class Credentials(BaseModel):
    username: str
    password: str


def _init_auth_storage():
    AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(AUTH_DB_PATH) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS users ("
            "id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)"
        )


def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    salt_hex, digest_hex = stored.split("$", 1)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), 120_000)
    return secrets.compare_digest(candidate.hex(), digest_hex)


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


def _get_agent(user_id: str) -> RAGCore:
    if user_id in agents:
        agents.move_to_end(user_id)
        return agents[user_id]

    while len(agents) >= AGENT_CACHE_SIZE:
        _evict_oldest_agent()

    user_dir = STORAGE_DIR / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "uploads").mkdir(parents=True, exist_ok=True)
    agent = RAGCore(upload_dir=str(user_dir / "uploads"), db_path=str(user_dir / "rag.sqlite3"))
    agents[user_id] = agent
    agents.move_to_end(user_id)
    return agent

@app.on_event("startup")
def startup_event():
    _init_auth_storage()
    _init_chat_history_storage()
    _reset_sqlalchemy_schema_if_needed()
    get_provider_settings()


@app.post("/auth/register")
def register(credentials: Credentials):
    username = credentials.username.strip()
    if len(username) < 3 or len(credentials.password) < 6:
        raise HTTPException(400, "Username must have 3 characters and password 6 characters")
    user_id = uuid4().hex
    try:
        with sqlite3.connect(AUTH_DB_PATH) as connection:
            connection.execute(
                "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                (user_id, username, _hash_password(credentials.password)),
            )
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username already exists")
    return {"message": "Account created"}


@app.post("/auth/login")
def login(credentials: Credentials):
    if User is not None and SessionLocal is not None:
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == credentials.username.strip()).first()
            if not user or not _verify_password(credentials.password, user.password_hash):
                raise HTTPException(401, "Invalid username or password")
        finally:
            db.close()

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
def get_provider_settings_route():
    return {"providers": get_provider_settings(), "supported": SUPPORTED_PROVIDERS, "active": LLM_PROVIDER}


@app.post("/settings/providers")
def save_provider_settings(payload: dict[str, str]):
    provider_name = (payload.get("provider") or "").strip().lower()
    if not provider_name:
        raise HTTPException(400, "provider is required")

    api_key = (payload.get("api_key") or "").strip()
    model_name = (payload.get("model_name") or "").strip()
    enabled = bool(payload.get("enabled", True))

    with sqlite3.connect(PROVIDER_SETTINGS_DB_PATH) as connection:
        connection.execute(
            "INSERT INTO provider_settings (provider, api_key, model_name, enabled, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(provider) DO UPDATE SET api_key=excluded.api_key, model_name=excluded.model_name, enabled=excluded.enabled, updated_at=excluded.updated_at",
            (provider_name, api_key, model_name, int(enabled), time.time()),
        )

    return {"provider": provider_name, "saved": True, "runtime": get_runtime_provider_config()}


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
    with sqlite3.connect(AUTH_DB_PATH) as connection:
        user = connection.execute(
            "SELECT username FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not user:
        raise HTTPException(404, "User not found")

    return {
        "user_id": user_id,
        "username": user[0],
        "provider_settings": get_provider_settings(),
        "supported_providers": SUPPORTED_PROVIDERS,
        "storage_dir": str(STORAGE_DIR / user_id),
    }


@app.get("/chat/history")
def chat_history(authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    return {"conversations": _get_user_conversations(user_id)}


@app.get("/chat/history/{conversation_id}")
def chat_history_detail(conversation_id: str, authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    return {"conversation_id": conversation_id, "messages": _get_conversation_messages(user_id, conversation_id)}


@app.post("/chat/save")
def save_chat_message(data: dict[str, Any], authorization: Optional[str] = Header(None)):
    user_id = _current_user(authorization)
    conversation_id = data.get("conversation_id")
    role = data.get("role", "user")
    content = str(data.get("content") or "")
    title = data.get("title")
    created_at = data.get("created_at")
    if not content:
        raise HTTPException(400, "content is required")
    return {"conversation_id": _save_chat_message(user_id, role, content, conversation_id, created_at, title)}


@app.get("/")
def root():
    return {
        "status": "ok",
        "provider": LLM_PROVIDER,
        "model": GOOGLE_MODEL if LLM_PROVIDER == "google" else OPENROUTER_MODEL if LLM_PROVIDER == "openrouter" else "huggingface",
        "vector_db_enabled": USE_VECTOR_DB
    }

@app.post("/upload_file")
async def upload_file(file: UploadFile = File(...), authorization: Optional[str] = Header(None)):
    """Accept PDF or image uploads. Extract text and add to agent's docs.
    Returns path and a short message. Multiple uploads can be sent in sequence.
    """
    agent = _get_agent(_current_user(authorization))

    # save file
    filename = Path(file.filename or "upload").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(415, "Unsupported file type")

    user_dir = STORAGE_DIR / _current_user(authorization)
    user_dir.mkdir(parents=True, exist_ok=True)
    out_path = user_dir / f"{uuid4().hex}{suffix}"
    try:
        content = await file.read()
        if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
            raise HTTPException(413, f"File exceeds the {MAX_UPLOAD_MB} MB limit")
        out_path.write_bytes(content)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to save file: {e}")

    # Detect file type from the validated extension.
    suf = out_path.suffix.lower()
    try:
        if suf == ".pdf":
            agent.add_pdf(str(out_path))
        elif suf in (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"):
            agent.add_image(str(out_path))
        else:
            agent.add_text(str(out_path))
    except Exception as e:
        raise HTTPException(500, f"Failed to ingest file: {e}")

    # optionally build vector DB
    if USE_VECTOR_DB and LANGCHAIN_AVAILABLE:
        try:
            agent.build_vector_db()
        except Exception as e:
            # don't block on vector DB build failure
            return {
                "message": "File uploaded, but vector DB build failed.",
                "detail": str(e),
                "path": str(out_path)
            }

    return {"message": "File uploaded and ingested.", "path": str(out_path)}

@app.post("/chat")
def chat(request: QueryRequest, authorization: Optional[str] = Header(None)):
    agent = _get_agent(_current_user(authorization))

    try:
        answer = agent.answer(request.question, k=request.k)
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/chat_with_image")
async def chat_with_image(
    question: str = Form(...),
    image: Optional[UploadFile] = File(None), 
    k: Optional[int] = Form(5),
    authorization: Optional[str] = Header(None)
):
    agent = _get_agent(_current_user(authorization))
    
    img_data = None
    if image is not None:
        try:
            img_stream = BytesIO(await image.read())
            img_data = Image.open(img_stream)
        except Exception as e:
            raise HTTPException(500, f"Failed to process image: {e}")

    try:
        answer = agent.answer(question, image=img_data, k=k)
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/summarize")
def summarize(authorization: Optional[str] = Header(None)):
    agent = _get_agent(_current_user(authorization))

    try:
        summaries = agent.summarize_all()
        return {"summaries": summaries}
    except Exception as e:
        raise HTTPException(500, str(e))


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
