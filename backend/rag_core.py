from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from PIL import Image
import requests

try:
    from .config import DB_PATH, EMBEDDING_MODEL, EMBEDDING_PROVIDER, UPLOAD_DIR, USE_VECTOR_DB, get_runtime_provider_config
    from .llm_provider import GeminiProvider, OpenRouterProvider
except ImportError:  # pragma: no cover
    from config import DB_PATH, EMBEDDING_MODEL, EMBEDDING_PROVIDER, UPLOAD_DIR, USE_VECTOR_DB, get_runtime_provider_config
    from llm_provider import GeminiProvider, OpenRouterProvider

try:
    from langchain_community.vectorstores import FAISS
    from langchain_core.documents import Document
    from langchain_core.embeddings import Embeddings
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    LANGCHAIN_AVAILABLE = True
except ImportError:  # pragma: no cover
    LANGCHAIN_AVAILABLE = False
    Embeddings = object

try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:  # pragma: no cover
    OCR_AVAILABLE = False


class OpenRouterEmbeddings(Embeddings):
    """LangChain-compatible embedding adapter that keeps vectors remote."""

    endpoint = "https://openrouter.ai/api/v1/embeddings"

    def __init__(self, api_key: str, model: str, site_url: str = "", app_name: str = ""):
        self.api_key = api_key
        self.model = model
        self.headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if site_url:
            self.headers["HTTP-Referer"] = site_url
        if app_name:
            self.headers["X-Title"] = app_name

    def _embed(self, texts: list[str]) -> list[list[float]]:
        payload: dict[str, Any] = {"model": self.model, "input": texts, "encoding_format": "float"}
        response = requests.post(self.endpoint, headers=self.headers, json=payload, timeout=90)
        response.raise_for_status()
        data = response.json().get("data", [])
        if len(data) != len(texts):
            raise RuntimeError("OpenRouter returned an incomplete embeddings response")
        return [item["embedding"] for item in sorted(data, key=lambda item: item["index"])]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector for offset in range(0, len(texts), 64) for vector in self._embed(texts[offset:offset + 64])]

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


class RAGCore:
    """Per-user persistent document store and retrieval pipeline."""

    def __init__(self, upload_dir: Optional[str] = None, db_path: Optional[str] = None, embedding_model: Optional[str] = None, user_id: Optional[str] = None):
        self.upload_dir = Path(upload_dir or UPLOAD_DIR)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path or DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path = self.db_path.parent / "faiss_index"
        self.embedding_model = embedding_model or EMBEDDING_MODEL
        self.user_id = user_id
        self.use_vector_db = USE_VECTOR_DB and LANGCHAIN_AVAILABLE
        self.vector_db = None
        self._embeddings = None
        self._init_storage()
        self._load_vector_db()

    def _connection(self):
        return sqlite3.connect(self.db_path, timeout=30)

    def _init_storage(self) -> None:
        with self._connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS documents (id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT, source TEXT NOT NULL, page_number INTEGER, text TEXT NOT NULL, content_hash TEXT, created_at REAL NOT NULL DEFAULT 0)")
            columns = {row[1] for row in connection.execute("PRAGMA table_info(documents)")}
            for name, definition in (("document_id", "TEXT"), ("page_number", "INTEGER"), ("content_hash", "TEXT"), ("created_at", "REAL NOT NULL DEFAULT 0")):
                if name not in columns:
                    connection.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_documents_document_id ON documents(document_id)")
            connection.execute("CREATE TABLE IF NOT EXISTS ingestion_jobs (document_id TEXT PRIMARY KEY, filename TEXT NOT NULL, status TEXT NOT NULL, detail TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)")

    def _embeddings_client(self):
        if self._embeddings is None:
            if EMBEDDING_PROVIDER == "openrouter":
                config = get_runtime_provider_config(self.user_id)
                if config["provider"] != "openrouter" or not config["api_key"]:
                    raise RuntimeError("OpenRouter embeddings require an active OpenRouter API key")
                self._embeddings = OpenRouterEmbeddings(
                    api_key=config["api_key"], model=self.embedding_model,
                    site_url=config.get("site_url", ""), app_name=config.get("app_name", ""),
                )
            elif EMBEDDING_PROVIDER == "local":
                self._embeddings = HuggingFaceEmbeddings(model_name=self.embedding_model)
            else:
                raise RuntimeError("EMBEDDING_PROVIDER must be 'local' or 'openrouter'")
        return self._embeddings

    def _load_vector_db(self) -> None:
        if not self.use_vector_db or not (self.index_path / "index.faiss").exists():
            return
        try:
            self.vector_db = FAISS.load_local(str(self.index_path), self._embeddings_client(), allow_dangerous_deserialization=True)
        except Exception:
            self.vector_db = None

    def create_ingestion_job(self, filename: str) -> str:
        document_id, now = uuid4().hex, time.time()
        with self._connection() as connection:
            connection.execute("INSERT INTO ingestion_jobs VALUES (?, ?, 'uploaded', 'Waiting to be processed', ?, ?)", (document_id, filename, now, now))
        return document_id

    def _set_job(self, document_id: str, status: str, detail: Optional[str] = None) -> None:
        with self._connection() as connection:
            connection.execute("UPDATE ingestion_jobs SET status=?, detail=?, updated_at=? WHERE document_id=?", (status, detail, time.time(), document_id))

    def get_job(self, document_id: str) -> Optional[dict[str, Any]]:
        with self._connection() as connection:
            row = connection.execute("SELECT document_id, filename, status, detail, created_at, updated_at FROM ingestion_jobs WHERE document_id=?", (document_id,)).fetchone()
        return dict(zip(("document_id", "filename", "status", "detail", "created_at", "updated_at"), row)) if row else None

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute("SELECT document_id, filename, status, detail, created_at, updated_at FROM ingestion_jobs ORDER BY created_at DESC").fetchall()
        keys = ("document_id", "filename", "status", "detail", "created_at", "updated_at")
        return [dict(zip(keys, row)) for row in rows]

    def get_document_page(self, document_id: str, page_number: int) -> Optional[dict[str, Any]]:
        """Return extracted text for a cited page, scoped to this user's store."""
        with self._connection() as connection:
            row = connection.execute(
                "SELECT source, page_number, text FROM documents WHERE document_id=? AND page_number=? LIMIT 1",
                (document_id, page_number),
            ).fetchone()
        if not row:
            return None
        return {"filename": Path(row[0]).name, "page_number": row[1], "text": row[2]}

    def _add_doc(self, document_id: str, source: str, text: str, page_number: Optional[int] = None) -> bool:
        text = text.strip()
        if not text:
            return False
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self._connection() as connection:
            if connection.execute("SELECT 1 FROM documents WHERE document_id=? AND content_hash=?", (document_id, content_hash)).fetchone():
                return False
            connection.execute("INSERT INTO documents (document_id, source, page_number, text, content_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)", (document_id, source, page_number, text, content_hash, time.time()))
        return True

    def _add_pdf(self, document_id: str, pdf_path: str) -> int:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        return sum(self._add_doc(document_id, pdf_path, page.extract_text() or "", index) for index, page in enumerate(reader.pages, start=1))

    def _add_image(self, document_id: str, image_path: str) -> int:
        text = pytesseract.image_to_string(Image.open(image_path)) if OCR_AVAILABLE else ""
        return int(self._add_doc(document_id, image_path, text or "[Image uploaded; no OCR text was detected.]", 1))

    def _add_text(self, document_id: str, text_path: str) -> int:
        return int(self._add_doc(document_id, text_path, Path(text_path).read_text(encoding="utf-8", errors="ignore"), 1))

    def ingest_file(self, document_id: str, path: str, display_name: Optional[str] = None) -> None:
        self._set_job(document_id, "processing")
        try:
            suffix = Path(path).suffix.lower()
            count = self._add_pdf(document_id, path) if suffix == ".pdf" else self._add_image(document_id, path) if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"} else self._add_text(document_id, path)
            if not count:
                raise ValueError("No extractable content was found in this file")
            if display_name:
                with self._connection() as connection:
                    connection.execute("UPDATE documents SET source=? WHERE document_id=?", (Path(display_name).name, document_id))
            self.build_vector_db()
            self._set_job(document_id, "ready", f"Indexed {count} page(s)/section(s)")
        except Exception as error:
            self._set_job(document_id, "failed", str(error)[:500])

    def _records(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute("SELECT document_id, source, page_number, text FROM documents ORDER BY id").fetchall()
        return [dict(zip(("document_id", "source", "page_number", "text"), row)) for row in rows]

    def build_vector_db(self, chunk_size: int = 900, chunk_overlap: int = 120) -> None:
        if not self.use_vector_db:
            return
        records = self._records()
        if not records:
            return
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        docs = [Document(page_content=row["text"], metadata={key: row[key] for key in ("document_id", "source", "page_number")}) for row in records]
        self.vector_db = FAISS.from_documents(splitter.split_documents(docs), self._embeddings_client())
        self.index_path.mkdir(parents=True, exist_ok=True)
        self.vector_db.save_local(str(self.index_path))

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token for token in re.findall(r"\w+", text.lower()) if len(token) > 2}

    def retrieve(self, query: str, k: int = 5) -> list[dict[str, Any]]:
        candidates = []
        if self.vector_db is not None:
            for document, distance in self.vector_db.similarity_search_with_score(query, k=max(k * 3, 10)):
                candidates.append({"text": document.page_content, **document.metadata, "semantic_score": float(distance)})
        if not candidates:
            candidates = self._records()
        terms = self._tokens(query)
        for item in candidates:
            item["lexical_score"] = len(terms & self._tokens(item["text"])) / max(len(terms), 1)
        candidates.sort(key=lambda row: (-row["lexical_score"], row.get("semantic_score", 0)))
        return candidates[:max(1, min(k, 10))]

    def _provider(self):
        config = get_runtime_provider_config(self.user_id)
        if config["provider"] == "google":
            return GeminiProvider(config["api_key"], config["model"])
        if config["provider"] == "openrouter":
            return OpenRouterProvider(config["api_key"], config["model"], config["site_url"], config["app_name"])
        raise RuntimeError(f"Unsupported LLM provider: {config['provider']}")

    def generate_text(self, messages: list[dict[str, str]] | str, image: Optional[Image.Image] = None, max_new_tokens: int = 512) -> str:
        prompt = messages if isinstance(messages, str) else "\n\n".join(f"{item['role'].upper()}: {item['content']}" for item in messages)
        return self._provider().generate(prompt, image=image, max_output_tokens=max_new_tokens)

    def answer_with_sources(self, question: str, image: Optional[Image.Image] = None, k: int = 5) -> dict[str, Any]:
        if image is not None:
            return {"answer": self.generate_text([{"role": "user", "content": f"Answer the question from this image: {question}"}], image=image), "sources": []}
        records = self._records()
        matches = self.retrieve(question, k) if records else []
        if records and not matches:
            return {"answer": "I could not find enough information in your uploaded documents to answer that question.", "sources": []}
        if matches:
            context = "\n\n".join(f"[Source: {Path(item['source']).name}, page {item.get('page_number') or 'N/A'}]\n{item['text']}" for item in matches)
            messages = [{"role": "system", "content": "Answer only from the supplied context. If it is insufficient, say so clearly. Do not invent facts."}, {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {question}"}]
        else:
            messages = [{"role": "user", "content": question}]
        answer = self.generate_text(messages)
        seen, sources = set(), []
        for item in matches:
            key = (item["source"], item.get("page_number"))
            if key not in seen:
                seen.add(key)
                sources.append({"document_id": item.get("document_id"), "filename": Path(item["source"]).name, "page_number": item.get("page_number")})
        return {"answer": answer, "sources": sources}

    def answer(self, question: str, image: Optional[Image.Image] = None, k: int = 5) -> str:
        return self.answer_with_sources(question, image=image, k=k)["answer"]

    def summarize_all(self, max_new_tokens: int = 192) -> list[dict[str, str]]:
        return [{"source": row["source"], "summary": self.generate_text(f"Summarize this text in 2-4 concise sentences:\n\n{row['text']}", max_new_tokens=max_new_tokens)} for row in self._records()]
