import os
import io
import shutil
from typing import Optional, List
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from io import BytesIO
from pydantic import BaseModel
from dotenv import load_dotenv
from pathlib import Path
import uvicorn
import nest_asyncio
from pyngrok import ngrok, conf


# ---------------------------------------------
# ---------------- FastAPI App ----------------
# ---------------------------------------------

app = FastAPI()
agent: Optional[RAGCore] = None

@app.on_event("startup")
def startup_event():
    global agent
    agent = RAGCore()

@app.get("/")
def root():
    return {
        "status": "ok",
        "model": MODEL_ID,
        "device": DEVICE,
        "vector_db_enabled": USE_VECTOR_DB
    }

@app.post("/upload_file")
async def upload_file(file: UploadFile = File(...)):
    """Accept PDF or image uploads. Extract text and add to agent's docs.
    Returns path and a short message. Multiple uploads can be sent in sequence.
    """
    global agent
    if agent is None:
        raise HTTPException(500, "Agent not initialized")

    # save file
    filename = Path(file.filename).name
    out_path = STORAGE_DIR / filename
    try:
        with open(out_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(500, f"Failed to save file: {e}")

    # detect file type
    suf = out_path.suffix.lower()
    try:
        if suf == ".pdf":
            agent.add_pdf(str(out_path))
        elif suf in (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif"):
            agent.add_image(str(out_path))
        else:
            # treat as text file
            text = out_path.read_text(encoding="utf-8", errors="ignore")
            agent.docs.append({"source": str(out_path), "text": text})
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
def chat(request: QueryRequest):
    global agent
    if agent is None:
        raise HTTPException(500, "Agent not initialized")

    try:
        answer = agent.answer(request.question, k=request.k)
        return {"answer": answer}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/chat_with_image")
async def chat_with_image(
    question: str = Form(...),
    image: Optional[UploadFile] = File(None), 
    k: Optional[int] = Form(5)
):
    global agent
    if agent is None:
        raise HTTPException(500, "Agent not initialized")
    
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
def summarize():
    global agent
    if agent is None:
        raise HTTPException(500, "Agent not initialized")

    try:
        summaries = agent.summarize_all()
        return {"summaries": summaries}
    except Exception as e:
        raise HTTPException(500, str(e))


# ---------------------------------------------
# ------------------- ngrok -------------------
# ---------------------------------------------
nest_asyncio.apply()

if __name__ == "__main__":

    # -------- ngrok config --------
    NGROK_TOKEN = "NGROK_TOKEN"
    conf.get_default().auth_token = NGROK_TOKEN

    ngrok.kill()

    public_url = ngrok.connect(8000)
    print("\n🔗 Your Public API URL:")
    print(public_url.public_url, "\n")

    uvicorn.run(app, host="0.0.0.0", port=8000)
