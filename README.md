
# Multimodal RAG Core

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/Ahmadgatany/Multimodal-RAG-Core/main?style=flat-square)
![License](https://img.shields.io/github/license/Ahmadgatany/Multimodal-RAG-Core?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)

Multimodal RAG Core is a client-server application for asking questions about uploaded documents and images. It combines a FastAPI backend, a Streamlit frontend, document extraction, optional OCR, semantic retrieval, and configurable model providers.

The application is designed around conversation isolation: every conversation has its own messages, uploaded files, SQLite document store, and FAISS index. A document uploaded in one conversation is not used as context in another conversation.

## Features

- Text questions over uploaded PDF, TXT, and Markdown files.
- Image questions using a vision-capable configured provider.
- PDF text extraction with page metadata.
- Optional OCR for uploaded images.
- Semantic retrieval with FAISS and LangChain when vector search is enabled.
- Local Hugging Face embeddings or OpenRouter embeddings.
- Provider-specific user settings with encrypted API-key storage.
- JWT authentication with access and refresh tokens.
- Conversation history, conversation switching, and deletion.
- Per-user rate limits, upload limits, retention cleanup, and health endpoints.
- Local development and production Docker Compose configurations.

## Supported Platforms

The project uses these three platform integrations:

1. **Google Gemini**: configurable LLM provider for text and image questions.
2. **OpenRouter**: configurable LLM provider and optional remote embedding provider.
3. **Hugging Face**: local sentence-transformer embeddings through LangChain.

The exact model names are selected through environment variables or the provider settings API. No specific model is required by this README.

## Architecture

```text
Streamlit frontend
	|
	| HTTP requests with JWT authentication
	v
FastAPI backend
	|
	+-- Conversation history (SQLite or configured database)
	+-- Conversation-scoped RAGCore
	|       +-- Uploaded files
	|       +-- Extracted document text
	|       +-- FAISS index
	|       +-- Ingestion jobs
	|
	+-- Google Gemini or OpenRouter for generation
	+-- Hugging Face or OpenRouter for embeddings
```

### Conversation isolation

Each chat request must include a `conversation_id`. The backend verifies that the conversation belongs to the authenticated user before reading or writing data. RAG agents are cached by `(user_id, conversation_id)`, and each conversation uses a separate storage directory:

```text
<UPLOAD_DIR>/<user_id>/conversations/<conversation_id>/
    rag.sqlite3
    faiss_index/
    uploads/
```

The Streamlit client also resets conversation-specific display state when creating or switching conversations.

## Project Structure

```text
Multimodal-RAG-Core/
|-- alembic.ini
|-- alembic/
|   |-- env.py
|   |-- script.py.mako
|   `-- versions/
|       `-- 20260831_auth_prod.py
|-- backend/
|   |-- app.py                 # FastAPI application and API routes
|   |-- config.py              # Environment configuration and provider settings
|   |-- database.py            # SQLAlchemy engine and session setup
|   |-- llm_provider.py        # Google and OpenRouter provider adapters
|   |-- models.py              # Authentication database models
|   `-- requirements.txt       # Backend dependencies
|-- docker/
|   |-- Dockerfile
|   `-- entrypoint.sh
|-- frontend/
|   |-- app.py                 # Streamlit client
|   `-- requirements.txt       # Frontend dependencies
|-- scripts/
|   `-- backup.ps1             # Database and upload backup script
|-- tests/
|   |-- load/locustfile.py     # Load-test scenarios
|   |-- test_auth_flow.py
|   |-- test_chat_history.py
|   |-- test_rag_pipeline.py
|   |-- test_scale_limits.py
|   `-- test_security_controls.py
|-- docker-compose.yml          # Development services
|-- docker-compose.production.yml
|-- requirements-dev.txt       # Development and load-test tools
|-- run.py                      # Starts backend and frontend locally
|-- test_system.ps1             # PowerShell system test helper
`-- README.md
```

Runtime data is intentionally excluded from the repository. It is created under `data/` or the configured storage paths and can include SQLite databases, uploaded files, ingestion jobs, and vector indexes.

## Local Setup

### 1. Create an environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Git Bash:

```bash
python -m venv .venv
source .venv/Scripts/activate
```

### 2. Install dependencies

Install backend and frontend dependencies from the project root:

```bash
pip install -r backend/requirements.txt
pip install -r frontend/requirements.txt
```

For development and load testing:

```bash
pip install -r requirements-dev.txt
```

### 3. Configure environment variables

Copy `.env.example` to `backend/.env` and set the required values. Keep `backend/.env` private and never commit it.

Minimum examples:

```dotenv
APP_ENV=development
LLM_PROVIDER=google
GOOGLE_API_KEY=your-google-api-key
GOOGLE_MODEL=your-google-model
EMBEDDING_PROVIDER=local
USE_VECTOR_DB=true
```

For OpenRouter generation, use:

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your-openrouter-api-key
OPENROUTER_MODEL=your-openrouter-model
```

For OpenRouter embeddings, set `EMBEDDING_PROVIDER=openrouter` and configure the embedding model and API key accordingly.

### 4. Start the application

From the project root:

```bash
python run.py
```

The services will be available at:

- Streamlit frontend: `http://localhost:8501`
- FastAPI backend: `http://localhost:8000`
- FastAPI health check: `http://localhost:8000/health`
- FastAPI interactive docs: `http://localhost:8000/docs`

The frontend can also be started separately:

```bash
streamlit run frontend/app.py --server.port 8501
```

If the backend is hosted elsewhere, set the frontend variable:

```dotenv
RAG_API_URL=https://your-backend-host.example.com
```

## Docker

Development configuration:

```bash
docker compose up --build
```

Production configuration:

```bash
docker compose -f docker-compose.production.yml up -d --build
```

Production mode requires secure values for the database, Redis, JWT secret, provider encryption key, provider API keys, and allowed origins. The backend exposes `/health` for liveness and `/ready` for readiness checks.

## API Overview

The backend provides endpoints for:

- Authentication: register, login, refresh, logout.
- Profile and provider settings.
- Conversation history, message storage, and conversation deletion.
- Conversation-scoped document upload and ingestion status.
- Text chat and image chat.
- Document listing and cited-page retrieval.
- Conversation-scoped summarization.
- Health, readiness, and authenticated metrics.

Interactive API documentation is available at `/docs` while the backend is running.

## Testing

Run the maintained test suite:

```bash
python -m pytest tests -q
```

Run load tests after starting the backend:

```bash
locust -f tests/load/locustfile.py --host http://localhost:8000
```

Create a local backup of configured databases and uploads with:

```powershell
.\scripts\backup.ps1
```

## Security Notes

- Do not commit `.env`, API keys, JWT secrets, SQLite databases, uploaded files, or vector indexes.
- Use PostgreSQL and Redis in production as required by the production configuration.
- Set `ALLOWED_ORIGINS` to the actual frontend origin.
- Provider API keys saved through the application are encrypted before storage.
- Conversation and document endpoints validate authenticated ownership.

## License

This project is licensed under the MIT License.
