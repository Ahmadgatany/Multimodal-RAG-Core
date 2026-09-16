# Multimodal RAG Core

> A production-oriented, multilingual document intelligence application. Upload a document, ask a question, and receive grounded answers from the content of that conversation.

**Multimodal RAG Core** combines a Next.js client with a FastAPI retrieval pipeline to deliver secure, conversation-scoped document Q&A. The interface and generated responses are designed for Arabic and English workflows.

## Why this project

- **Grounded answers** — retrieves relevant passages before asking the model to answer, with filename and page references returned alongside the response.
- **Strict data isolation** — every user and conversation has an independent document store; uploads never cross conversation boundaries.
- **Multimodal input** — supports PDFs, text, Markdown, and common image formats, as well as image-based questions.
- **Bring your own key** — users can securely save and enable their own Google Gemini or OpenRouter API key from Model Settings.
- **Production safeguards** — Google sign-in, JWT access and refresh tokens, rate limits, encrypted provider keys, health checks, PostgreSQL, Redis, Docker, and explicit production validation.

## Product flow

```text
Sign in with Google
       ↓
Create or select a conversation
       ↓
Upload documents / ask a question
       ↓
Extract, chunk, and retrieve relevant content
       ↓
Generate an answer with source metadata
```

Each account receives **one server-provided free question**. Afterwards, the application guides the user to Model Settings to add and enable their own API key.

## Architecture

```text
┌───────────────────────────────────────────────┐
│ Next.js 15 + React 19 frontend                 │
│ Google OAuth · conversations · model settings  │
└───────────────────────┬───────────────────────┘
                        │ HTTPS / JWT
┌───────────────────────▼───────────────────────┐
│ FastAPI application                            │
│ auth · uploads · chat · provider configuration │
└───────┬───────────────────────┬───────────────┘
        │                       │
┌───────▼────────┐     ┌────────▼──────────────┐
│ PostgreSQL      │     │ Conversation RAG store │
│ users/sessions  │     │ SQLite + optional FAISS│
└────────────────┘     └────────┬──────────────┘
                                 │
                   ┌─────────────▼─────────────┐
                   │ Gemini or OpenRouter model │
                   └───────────────────────────┘
```

Conversation data is persisted independently at:

```text
<UPLOAD_DIR>/<user_id>/conversations/<conversation_id>/
├── uploads/
├── rag.sqlite3
└── faiss_index/                 # created when vector search is enabled
```

## Core capabilities

| Area | Details |
| --- | --- |
| Authentication | Google OAuth with JWT access and refresh tokens |
| Conversations | Saved history, isolated documents, and per-conversation retrieval |
| Files | PDF, TXT, Markdown, PNG, JPG/JPEG, TIFF, BMP, and GIF |
| Extraction | PDF text extraction and optional Tesseract OCR for images |
| Retrieval | SQLite-backed chunks with optional FAISS vector search |
| Models | Google Gemini and OpenRouter; text and image prompts |
| User model settings | Encrypted, per-user API keys with provider/model selection and enablement |
| Operational safety | File-size cap, rate limits, ownership checks, readiness and metrics endpoints |

> Uploads and image-question attachments are capped at **2 MB** by design.

## Technology

| Layer | Stack |
| --- | --- |
| Web client | Next.js 15, React 19, TypeScript, Lucide |
| API | FastAPI, Uvicorn/Gunicorn, Pydantic |
| Persistence | PostgreSQL in production; SQLite for RAG data |
| Caching / rate limiting | Redis |
| Retrieval | LangChain, FAISS, sentence-transformers |
| Document processing | pypdf, Pillow, optional Tesseract OCR |
| AI providers | Google Gen AI SDK and OpenRouter API |
| Deployment | Docker Compose and Railway-compatible configuration |

## Repository layout

```text
.
├── backend/
│   ├── app.py                 # FastAPI routes and API orchestration
│   ├── config.py              # environment, validation, provider settings
│   ├── rag_core.py            # ingestion, retrieval, and answer generation
│   ├── llm_provider.py        # Gemini and OpenRouter adapters
│   ├── database.py            # SQLAlchemy database setup
│   └── requirements.txt
├── frontend/                  # Next.js application
├── tests/                     # API, RAG, security, and scale tests
├── docker/                    # backend image and container entrypoint
├── docker-compose.yml         # local production-like services
├── docker-compose.production.yml
├── run.py                     # local development launcher
└── .env.example               # environment template
```

## Quick start

### Prerequisites

- Python 3.10+
- Node.js 18.18+ and npm
- A Google OAuth Web Client ID
- A Gemini or OpenRouter API key for the server-provided free question
- Tesseract, only when image OCR is required

### 1. Install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r backend/requirements.txt
pip install -r requirements-dev.txt  # optional: test and load-test tooling

cd frontend
npm install
cd ..
```

### 2. Configure the environment

Copy `.env.example` to `backend/.env`. This file is ignored by Git and must never be committed.

```dotenv
# backend/.env
APP_ENV=development
GOOGLE_OAUTH_CLIENT_ID=your-google-oauth-web-client-id.apps.googleusercontent.com
GOOGLE_API_KEY=your-server-gemini-api-key
GOOGLE_MODEL=gemini-2.5-flash
LLM_PROVIDER=google
EMBEDDING_PROVIDER=local
USE_VECTOR_DB=true
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

Create `frontend/.env.local` for browser-visible variables:

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID=your-google-oauth-web-client-id.apps.googleusercontent.com
```

The Google OAuth client ID must match in both files. For OpenRouter as the server provider, set `LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY`, and `OPENROUTER_MODEL` instead.

### 3. Run locally

From the repository root:

```powershell
python run.py
```

Or run the services separately:

```powershell
# terminal 1
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000

# terminal 2
cd frontend
npm run dev
```

Open the application at `http://localhost:3000`.

| Service | URL |
| --- | --- |
| Frontend | `http://localhost:3000` |
| API health | `http://localhost:8000/health` |
| API readiness | `http://localhost:8000/ready` |
| API documentation | `http://localhost:8000/docs` |
| Metrics | `http://localhost:8000/metrics` |

## Model providers and user API keys

The application can use a server-configured provider for the initial free question. To continue, users open **Model Settings**, choose **Google Gemini** or **OpenRouter**, enter an API key, select a model, enable that provider, and save.

Provider keys are encrypted before being stored. A user key takes precedence over the server default for that user; users can update the key or choose another supported provider later.

## Deployment

### Docker Compose

Docker Compose runs the API with PostgreSQL and Redis. The Next.js frontend is deployed separately, or started locally, and must receive the public backend URL through `NEXT_PUBLIC_API_URL`.

```bash
docker compose up --build
docker compose -f docker-compose.production.yml up -d --build
```

Before production, set at least:

```dotenv
APP_ENV=production
DATABASE_URL=postgresql+psycopg://...
REDIS_URL=redis://...
JWT_SECRET_KEY=<unique secret of at least 32 characters>
PROVIDER_ENCRYPTION_KEY=<valid Fernet key>
ALLOWED_ORIGINS=https://your-frontend.example.com
```

The backend fails fast in production when PostgreSQL, Redis, a valid Fernet key, a strong JWT secret, or safe CORS origins are missing.

### Railway

Create four Railway services: **backend**, **frontend**, **PostgreSQL**, and **Redis**.

| Service | Configuration |
| --- | --- |
| Backend | Root directory `/`; Dockerfile `docker/Dockerfile`; health check `/health` |
| Frontend | Root directory `/frontend`; build `npm run build`; start `npm start` |
| PostgreSQL / Redis | Use Railway-managed services and reference variables |

Attach a persistent backend volume at `/app/data` to retain uploaded files, SQLite RAG stores, and FAISS indexes. Set `NEXT_PUBLIC_API_URL` to the backend's public HTTPS address, and set the exact frontend HTTPS origin in `ALLOWED_ORIGINS`. Rebuild the frontend after changing `NEXT_PUBLIC_API_URL` because Next.js exposes it at build time.

### Current hosted deployment

[Open the deployed application](https://multimodal-rag-core-production-4615.up.railway.app/)

Hosted on Railway. Availability may be temporary through October 14, 2026.

## Verification and testing

```powershell
# backend tests
python -m pytest tests -q

# frontend production build
cd frontend
npm run build

# optional load test (start the backend first)
locust -f tests/load/locustfile.py --host http://localhost:8000
```

Recommended release checks:

1. Confirm `/health` and `/ready` return successfully.
2. Sign in through Google OAuth.
3. Upload a small PDF or text document and ask a grounded question.
4. Verify that returned citations match the uploaded filename and page.
5. Confirm the public frontend origin is the only allowed browser origin.

## Security and operational notes

- Never commit `.env`, `.env.local`, API keys, uploads, databases, or vector indexes.
- Rotate a key immediately if it appears in a commit, terminal capture, screenshot, or chat.
- Use HTTPS and exact origins in `ALLOWED_ORIGINS` for every production environment.
- Keep PostgreSQL, Redis, and the `/app/data` volume backed up according to your retention policy.
- API routes verify that the authenticated user owns the relevant conversation and document.
- The built-in upload limit is intentionally capped at 2 MB, even if an environment value is higher.

## License

Licensed under the MIT License.
