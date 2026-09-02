
# Multimodal RAG Core

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/Ahmadgatany/Multimodal-RAG-Core/main?style=flat-square)
![License](https://img.shields.io/github/license/Ahmadgatany/Multimodal-RAG-Core?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-blue)

A Multimodal RAG System with a provider-independent FastAPI backend and Streamlit client. The default provider is OpenRouter, configured for `minimax/minimax-m3:free`; Google Gemini and Hugging Face remain available as alternatives.

---

## 🚀 Key Features

* **Multimodal Q&A:** Answer questions based on uploaded images (Vision-Language).
* **Document RAG:** Context-aware answers and summarization from PDFs and text files using LangChain and FAISS.
* **OCR Integration:** Extract text from images and documents to enhance retrieval accuracy.
* **Provider boundary:** Switch model providers through environment variables without changing the RAG API.
* **Local client connection:** Streamlit connects directly to the local FastAPI service; set `RAG_API_URL` only when the API runs elsewhere.

## 📐 Project Architecture

This project employs a client-server architecture designed to leverage cloud GPUs while maintaining a local, interactive user experience:

| Component | Technology | Role | Location |
| :--- | :--- | :--- | :--- |
| **Backend** (Server) | FastAPI, Qwen-VL, PyTorch, FAISS | Handles file ingestion, RAG pipeline, LLM inference, and summarization. | **Cloud (Kaggle/Colab GPU)** |
| **Frontend** (Client) | Streamlit, Requests | Provides the interactive chat interface and connects directly to the local FastAPI service. | **Local Machine** |
| **Core Model** | Google Gemini (configurable) | Vision-Language Model used for generation and multimodal understanding. | Google API |

---

## 🛠️ Setup and Installation

### 1. Backend Setup

The backend handles ingestion, retrieval, and model requests. OpenRouter does not require a local GPU.

#### A. Install dependencies

Install the backend dependencies:

```bash
cd backend
pip install -r requirements.txt
```

#### B. Configuration

Create `backend/.env` and add an OpenRouter API key. Keep this file private:

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY="YOUR_OPENROUTER_API_KEY_HERE"
OPENROUTER_MODEL=minimax/minimax-m3:free
```

#### D. Execution

From the project root, start the backend and frontend together with one command:

```powershell
python run.py
```

The local API is available at `http://localhost:8000` and Streamlit at `http://localhost:8501`. Press `Ctrl+C` once to stop both services.

### Production operations

Run the isolated production stack (no source-code bind mounts) with `docker compose -f docker-compose.production.yml up -d --build`. Configure the required secrets and public `ALLOWED_ORIGINS` in `.env` first. The API exposes `/health` for liveness and `/ready` for database/Redis readiness; `/metrics` is authenticated and returns a small non-sensitive operational summary.

Create a database-plus-upload backup with `./scripts/backup.ps1`. Install `requirements-dev.txt` and run `locust -f tests/load/locustfile.py --host http://localhost:8000 -u 30 -r 3 -t 10m` before deployment to exercise 30 concurrent chat/upload users.

### 2\. Frontend Setup (Local Machine)

The frontend runs the lightweight Streamlit client.

#### A. Dependencies

Install the required packages locally:

```bash
cd frontend
pip install -r requirements.txt
```

#### B. Execution

The launcher starts Streamlit automatically. It connects to `http://localhost:8000` without asking for a server URL. To use another API host, set `RAG_API_URL` before starting Streamlit.

## 🤝 Contribution

Feel free to open issues or submit pull requests. All feedback is welcome\!

## 📜 License

This project is licensed under the MIT License - see the LICENSE file for details.

```
```
