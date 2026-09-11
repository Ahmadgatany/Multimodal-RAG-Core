# Multimodal RAG Core

Multimodal RAG Core is a document question-answering application. Upload a PDF, text file, Markdown file, or image, then ask questions in a conversation. The application retrieves relevant content from the files in that conversation and sends it to a configured AI model to produce an answer with source references.

The project has a FastAPI backend and a Next.js frontend. It supports Arabic and English user interfaces and responses.

## What it does

- Authenticated accounts with JWT access and refresh tokens.
- Independent conversations with saved message history.
- Conversation-scoped uploads: files in one conversation are never used in another.
- PDF, TXT, Markdown, and common image uploads.
- PDF text extraction and optional OCR for images.
- Retrieval-augmented generation (RAG) with SQLite storage and an optional FAISS vector index.
- Source filename and page metadata in chat results.
- Text and image questions through Google Gemini or OpenRouter.
- Per-user provider configuration with encrypted stored API keys.
- Rate limits, upload limits, health/readiness endpoints, and production checks.

## Architecture

```text
Next.js frontend (port 3000)
        |
        | HTTP + JWT
        v
FastAPI backend (port 8000)
        |
        +-- Authentication and conversation history
        +-- One RAGCore store per user and conversation
        |     +-- uploads
        |     +-- extracted text in SQLite
        |     +-- optional FAISS index
        |
        +-- Google Gemini / OpenRouter: answer generation
        +-- Gemini / OpenRouter / local Hugging Face: embeddings
```

Each conversation is stored separately under:

```text
<UPLOAD_DIR>/<user_id>/conversations/<conversation_id>/
├── uploads/
├── rag.sqlite3
└── faiss_index/                 # created when vector search is enabled
```

## Technology

| Area | Tools |
| --- | --- |
| Frontend | Next.js 15, React 19, TypeScript, Lucide icons |
| API | FastAPI, Uvicorn, Pydantic |
| Authentication | JWT, PyJWT, refresh-token storage |
| RAG | LangChain, FAISS, SQLite |
| Document processing | pypdf, Pillow, optional Tesseract OCR |
| Models | Google Gen AI SDK, OpenRouter API |
| Local embeddings | sentence-transformers / Hugging Face |
| Production services | PostgreSQL, Redis, Gunicorn, Docker Compose |

## Project structure

```text
Multimodal-RAG-Core/
├── backend/
│   ├── app.py                  # FastAPI routes
│   ├── config.py               # environment and provider settings
│   ├── rag_core.py             # ingestion, retrieval, and generation
│   ├── llm_provider.py         # Gemini and OpenRouter adapters
│   ├── database.py / models.py # production authentication persistence
│   └── requirements.txt
├── frontend/                   # Next.js application
│   ├── app/
│   ├── package.json
│   └── .env.local.example
├── tests/                      # API, RAG, security, and scale tests
├── docker/                     # backend container image and entrypoint
├── docker-compose.yml          # PostgreSQL, Redis, backend stack
├── docker-compose.production.yml
├── run.py                      # starts backend and Next.js locally
└── .env.example                # backend environment template
```

Runtime data and secrets are excluded from version control. When `backend/.env` uses relative data paths, they resolve relative to `backend/`.

## Local setup

### Prerequisites

- Python 3.10 or newer
- Node.js 18.18 or newer with npm
- A Google Gemini or OpenRouter API key for generation
- Tesseract only if image OCR is required

### 1. Create and activate a Python environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
pip install -r backend/requirements.txt
pip install -r requirements-dev.txt   # optional: tests and load testing

cd frontend
npm install
cd ..
```

### 3. Configure the backend

Copy `.env.example` to `backend/.env` and set your keys. Do not commit this file.

Minimal Gemini configuration:

```dotenv
APP_ENV=development
LLM_PROVIDER=google
GOOGLE_API_KEY=your-google-api-key
GOOGLE_MODEL=gemini-2.5-flash
EMBEDDING_PROVIDER=local
USE_VECTOR_DB=true
ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
```

For OpenRouter generation:

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_MODEL=your-openrouter-model
```

To point the browser application at a non-local backend, create `frontend/.env.local`:

```dotenv
NEXT_PUBLIC_API_URL=https://your-backend.example.com
```

### 4. Run the application

From the repository root:

```powershell
python run.py
```

Or start each service separately:

```powershell
# terminal 1
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000

# terminal 2
cd frontend
npm run dev
```

Open:

- Frontend: `http://localhost:3000`
- Backend health: `http://localhost:8000/health`
- Backend readiness: `http://localhost:8000/ready`
- API documentation: `http://localhost:8000/docs`

## Docker and production

The Compose files run the backend with PostgreSQL and Redis. The Next.js frontend is started or deployed separately; configure its `NEXT_PUBLIC_API_URL` to the public backend URL.

```bash
docker compose up --build
docker compose -f docker-compose.production.yml up -d --build
```

Production requires PostgreSQL, Redis, a strong `JWT_SECRET_KEY`, a valid `PROVIDER_ENCRYPTION_KEY`, model-provider credentials, and the actual frontend URL in `ALLOWED_ORIGINS`.

## Deploy on Railway

Deploy this repository as one Railway project with four services: **backend**, **frontend**, **PostgreSQL**, and **Redis**. AI inference is supplied by Gemini or OpenRouter; Railway hosts the application, not the model weights.

### 1. Push to GitHub

Create an empty GitHub repository, then push this project. Do not include `backend/.env`, uploaded data, databases, or API keys.

```powershell
git init
git add .
git commit -m "Prepare Railway deployment"
git branch -M main
git remote add origin https://github.com/YOUR_ACCOUNT/YOUR_REPOSITORY.git
git push -u origin main
```

### 2. Create Railway services

In Railway, create an empty project, add **PostgreSQL** and **Redis**, then add the same GitHub repository twice:

| Service | Railway setting |
| --- | --- |
| `backend` | Root Directory: `/`; Dockerfile Path: `docker/Dockerfile`; Healthcheck Path: `/health` |
| `frontend` | Root Directory: `/frontend`; Build Command: `npm run build`; Start Command: `npm start` |

Generate a public domain for the backend first. The browser frontend calls this public URL directly.

### 3. Backend variables

Set these in the backend service. Add `DATABASE_URL` and `REDIS_URL` as reference variables from the Railway PostgreSQL and Redis services rather than copying credentials.

```dotenv
APP_ENV=production
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
JWT_SECRET_KEY=<a unique random secret of at least 32 characters>
PROVIDER_ENCRYPTION_KEY=<a Fernet key>
LLM_PROVIDER=google
GOOGLE_API_KEY=<your key>
GOOGLE_MODEL=gemini-2.5-flash
EMBEDDING_PROVIDER=local
USE_VECTOR_DB=true
UPLOAD_DIR=/app/data/uploads
DATA_DIR=/app/data
GUNICORN_WORKERS=1
RAILWAY_RUN_UID=0
```

Also attach a Railway **Volume** to the backend at `/app/data`. This preserves uploads, SQLite-backed conversation/RAG data, and FAISS indexes across deployments. `RAILWAY_RUN_UID=0` is required here because the Docker image uses a non-root application user while Railway volumes are mounted as root-owned.

### 4. Frontend variables and CORS

Generate a public domain for the frontend, then set:

```dotenv
# frontend service
NEXT_PUBLIC_API_URL=https://YOUR-BACKEND.up.railway.app

# backend service
ALLOWED_ORIGINS=https://YOUR-FRONTEND.up.railway.app
```

Redeploy the frontend after changing `NEXT_PUBLIC_API_URL`, because Next.js exposes this value to the browser during its build. Use the exact HTTPS origins without a trailing slash.

### 5. Verify

- Open the frontend domain and register an account.
- Visit `https://YOUR-BACKEND.up.railway.app/health`; it should return a healthy response.
- Upload a small text or PDF file, wait for ingestion, and send a chat question.
- Check Railway deployment logs if the backend healthcheck or the browser API request fails.

Railway deployment uses GitHub as the source, so every push to the configured branch triggers a new deployment. Railway supports GitHub deployment and public domains for Next.js services, custom Dockerfile paths for backend services, and persistent volumes for files that must survive deployments. [Railway Next.js guide](https://docs.railway.com/guides/nextjs), [Dockerfile configuration](https://docs.railway.com/builds/dockerfiles), and [volumes](https://docs.railway.com/volumes).

## Testing

Run the automated suite from the repository root:

```powershell
python -m pytest tests -q
```

Build-check the frontend:

```powershell
cd frontend
npm run build
```

For load testing, start the backend then run:

```powershell
locust -f tests/load/locustfile.py --host http://localhost:8000
```

## Security notes

- Never commit `.env` files, API keys, databases, uploads, or FAISS indexes.
- Rotate any API key that has been exposed in a terminal, screenshot, commit, or chat.
- Configure `ALLOWED_ORIGINS` with the exact public frontend URL in production.
- Provider keys saved from the application are encrypted before being persisted.
- API routes verify the authenticated owner of conversations and documents.

## License

MIT License.
