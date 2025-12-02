import os
import torch
from typing import Optional, List, Dict
from pathlib import Path
from PIL import Image

# --- Transformers ---
from transformers import (
    AutoTokenizer, 
    AutoModelForCausalLM, 
    AutoProcessor, 
    AutoModelForVision2Seq, 
    pipeline
)

# -------------------
try:
    from langchain_community.vectorstores import FAISS
    from langchain_community.document_loaders import PyPDFLoader
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    from langchain.schema import Document
    from langchain_huggingface.embeddings import HuggingFaceEmbeddings
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    print("Warning: LangChain not found. Vector DB features will be disabled.")

# --- OCR ---
try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# --- PDF Fallback  ---
try:
    from PyPDF2 import PdfReader
except ImportError:
    pass

class RAGCore:
 

    def __init__(
        self,
        model_id: Optional[str] = None,
        embedding_model: Optional[str] = None,
        device: Optional[str] = None,
        upload_dir: Optional[str] = None,
        use_vector_db: Optional[bool] = None,
    ):
        # Defaults (fall back to env or sane defaults)
        self.model_id = model_id or os.getenv("HF_MODEL_ID", "Qwen/Qwen2.5-VL-7B-Instruct")
        self.embedding_model = embedding_model or os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-mpnet-base-v2")
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.upload_dir = Path(upload_dir or os.getenv("UPLOAD_DIR", "/tmp/agentic_uploads"))
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.use_vector_db = use_vector_db if use_vector_db is not None else os.getenv("USE_VECTOR_DB", "True").lower() in ("1","true","yes")

        # Model placeholders
        self.tokenizer = None
        self.model = None
        self.processor = None     # for VL models
        self.text_gen = None      # pipeline for text-only models
        self.model_is_vl = False

        # Document storage: list of dicts { "source": str, "text": str }
        self.docs: List[Dict[str, str]] = []

        # Vector DB placeholder
        self.vector_db = None

        # detect if LangChain available
        try:
            import langchain   # just to test import
            self._langchain_available = True
        except Exception:
            self._langchain_available = False

        # detect OCR availability
        try:
            import pytesseract  # noqa: F401
            self._ocr_available = True
        except Exception:
            self._ocr_available = False

        # load model (may raise informative errors)
        self._load_model()

    def _get_model_device(self):
        try:
            first_param = next(self.model.parameters())
            return first_param.device
        except Exception:
            return torch.device(self.device if self.device in ("cuda","cpu") else "cpu")

    def _load_model(self):
        """Load tokenizer + model; handle text-only and vision+language variants carefully."""
        try:
            print("[core] Loading model:", self.model_id, "on", self.device)
            mid = (self.model_id or "").lower()
            is_vl = "qwen" in mid and ("-vl" in mid or mid.endswith("vl") or "vl-" in mid)
            if is_vl:
                # Try to load VL-capable model. This requires a recent transformers & vendor code.
                try:
                    from transformers import AutoTokenizer, AutoProcessor
                    # Some environments provide a generic Vision2Seq wrapper; try its import dynamically:
                    try:
                        from transformers import AutoModelForVision2Seq  # may not exist
                        self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, use_fast=True)
                        self.processor = AutoProcessor.from_pretrained(self.model_id)
                        self.model = AutoModelForVision2Seq.from_pretrained(
                            self.model_id,
                            torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                            device_map="auto" if torch.cuda.is_available() else None,
                            trust_remote_code=True,
                        )
                        self.model_is_vl = True
                        self.text_gen = None
                        print("[core] Loaded as vision+language (AutoModelForVision2Seq).")
                        return
                    except Exception:
                        # fallback to vendor-specific Qwen class if available
                        try:
                            # Many vendor models expose QwenForConditionalGeneration-like class
                            from transformers import AutoTokenizer, AutoProcessor
                            from transformers import QwenForConditionalGeneration  # may not exist in env
                            self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, use_fast=True)
                            self.processor = AutoProcessor.from_pretrained(self.model_id)
                            self.model = QwenForConditionalGeneration.from_pretrained(
                                self.model_id,
                                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                                device_map="auto" if torch.cuda.is_available() else None,
                                trust_remote_code=True,
                            )
                            self.model_is_vl = True
                            self.text_gen = None
                            print("[core] Loaded as vision+language (QwenForConditionalGeneration).")
                            return
                        except Exception as e_qwen:
                            raise RuntimeError(
                                "Vision+Language model detected but required classes are missing. "
                                "Install or upgrade 'transformers' (possibly from GitHub) and any model-specific packages. "
                                f"Inner error: {e_qwen}"
                            ) from e_qwen
                except Exception as e_proc:
                    raise RuntimeError(
                        "Failed to import AutoTokenizer/AutoProcessor for VL model. "
                        "Ensure 'transformers' is updated and 'trust_remote_code' may be required."
                        f" Inner error: {e_proc}"
                    ) from e_proc

            # text-only model fallback
            try:
                from transformers import AutoTokenizer, AutoModelForCausalLM, pipeline
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_id, use_fast=True)
                self.model = AutoModelForCausalLM.from_pretrained(
                    self.model_id,
                    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                    device_map="auto" if torch.cuda.is_available() else None,
                    trust_remote_code=True,
                )
                # try to create a pipeline (if it fails, we'll still use model.generate)
                try:
                    self.text_gen = pipeline(
                        "text-generation",
                        model=self.model,
                        tokenizer=self.tokenizer,
                        device=0 if torch.cuda.is_available() else -1,
                        max_new_tokens=512,
                        do_sample=False,
                    )
                except Exception:
                    self.text_gen = None
                self.model_is_vl = False
                print("[core] Loaded as text-only model.")
                return
            except Exception as e_text:
                raise RuntimeError(
                    "Failed to load text model. Ensure 'transformers' is installed and model_id is correct. "
                    f"Inner error: {e_text}"
                ) from e_text

        except Exception as e:
            print("[core] Model load failed:", e)
            raise

    # ---------------- File ingestion helpers ----------------
    def add_pdf(self, pdf_path: str):
        """Extract text from a PDF and append to docs. Uses langchain.PyPDFLoader if available, else PyPDF2."""
        p = Path(pdf_path)
        if not p.exists():
            raise FileNotFoundError(pdf_path)

        # try langchain loader first (if installed)
        if self._langchain_available:
            try:
                from langchain_community.document_loaders import PyPDFLoader
                loader = PyPDFLoader(str(pdf_path))
                pages = loader.load()
                for pg in pages:
                    self.docs.append({"source": str(pdf_path), "text": pg.page_content})
                return
            except Exception:
                # fallback to PyPDF2 below
                pass

        # fallback: PyPDF2
        try:
            from PyPDF2 import PdfReader
            reader = PdfReader(str(pdf_path))
            for page in reader.pages:
                txt = page.extract_text() or ""
                if txt.strip():
                    self.docs.append({"source": str(pdf_path), "text": txt})
            return
        except Exception as e:
            raise RuntimeError(f"Failed to extract text from PDF: {e}") from e

    def add_image(self, img_path: str):
        """Extract text from image using OCR if available; otherwise store placeholder reference."""
        p = Path(img_path)
        if not p.exists():
            raise FileNotFoundError(img_path)

        extracted = ""
        if self._ocr_available:
            try:
                import pytesseract
                img = Image.open(str(img_path))
                extracted = pytesseract.image_to_string(img)
            except Exception:
                extracted = ""
        if not extracted:
            # store a small placeholder hint so that user knows image exists
            extracted = f"[no OCR text] Image saved at: {img_path}"
        self.docs.append({"source": str(img_path), "text": extracted})

    # ---------------- Vector DB ----------------
    def build_vector_db(self, chunk_size: int = 1000, chunk_overlap: int = 100):
        """Build FAISS vector DB from self.docs using HuggingFace embeddings via LangChain (if available)."""
        if not self._langchain_available:
            raise RuntimeError("LangChain components are not available in this environment. Install langchain_community and langchain.")

        # import lazily
        try:
            from langchain.text_splitter import RecursiveCharacterTextSplitter
            from langchain.schema import Document
            from langchain_huggingface.embeddings import HuggingFaceEmbeddings
            from langchain_community.vectorstores import FAISS
        except Exception as e:
            raise RuntimeError(f"Missing LangChain components for vector DB build: {e}") from e

        # assemble docs into LangChain Document objects
        lc_docs = []
        for d in self.docs:
            lc_docs.append(Document(page_content=d["text"], metadata={"source": d["source"]}))

        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        chunks = splitter.split_documents(lc_docs)
        embeddings = HuggingFaceEmbeddings(model_name=self.embedding_model)
        self.vector_db = FAISS.from_documents(chunks, embeddings)
        print("[core] Vector DB built with", len(chunks), "chunks.")

    def get_local_content(self, query: str, k: int = 5) -> str:
        """Return concatenated top-k chunk texts from vector DB if available, otherwise naive substring search across docs."""
        if self.vector_db is not None:
            try:
                docs = self.vector_db.similarity_search(query, k=k)
                return "\n\n".join(d.page_content for d in docs)
            except Exception:
                # fallback to naive
                pass

        # naive substring search
        matches = []
        for d in self.docs:
            if query.lower() in d["text"].lower():
                matches.append(d["text"])
                if len(matches) >= k:
                    break
        return "\n\n".join(matches)

    # ---------------- Summarization helper ----------------
    def summarize_all(self, max_new_tokens: int = 192) -> List[Dict[str, str]]:
        """Summarize each uploaded doc using the loaded model."""
        summaries = []
        for d in self.docs:
            text = d.get("text", "")
            prompt = (
                "Summarize the following text in 2-4 concise sentences, highlighting key points.\n\n"
                f"TEXT:\n{text}\n\nSummary:"
            )
            try:
                s = self.generate_text(prompt, max_new_tokens=max_new_tokens)
            except Exception as e:
                s = f"[summary failed: {e}]"
            summaries.append({"source": d.get("source"), "summary": s})
        return summaries

    # ---------------- Generation & Answering ----------------
    def generate_text(self, messages: List[Dict[str, str]], image: Optional[Image.Image] = None, max_new_tokens: int = 512) -> str:
        """
        Generate text handling Chat Templates correctly to avoid repetition.
        messages example: [{"role": "user", "content": "Hello..."}]
        """
        # 1. Prepare inputs using Chat Template
        text_prompt = self.processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        
        inputs = None
        if self.model_is_vl and image is not None:
            inputs = self.processor(text=[text_prompt], images=image, return_tensors="pt", padding=True)
        else:
          
            if self.model_is_vl:
                inputs = self.processor(text=[text_prompt], images=None, return_tensors="pt")
            else:
                inputs = self.tokenizer(text_prompt, return_tensors="pt")

        # Move to device
        model_device = self._get_model_device()
        for k, v in inputs.items():
            if isinstance(v, torch.Tensor):
                inputs[k] = v.to(model_device)

        # 2. Generate with Stop Configs (To fix repetition)
        try:
            gen_output = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=True,         
                temperature=0.7,        
                top_p=0.9,
                repetition_penalty=1.1,  
                pad_token_id=self.tokenizer.pad_token_id,
                eos_token_id=self.tokenizer.eos_token_id  
            )
            
            # Decode output
            input_len = inputs.input_ids.shape[1]
            generated_ids = gen_output[0][input_len:]
            text = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
            return text.strip()
            
        except Exception as e:
            raise RuntimeError(f"Generation failed: {e}") from e

    def answer(self, question: str, image: Optional[Image.Image] = None, k: int = 5) -> str:
        messages = []
        
        # --- Case 1: Image ---
        if image is not None:
            content = f"Answer this question based on the image: {question}"
            messages = [{"role": "user", "content": content}]
            return self.generate_text(messages, image=image)

        # --- Case 2: RAG Context ---
        context = ""
        if self.docs:
            if self.vector_db:
                try:
                    docs = self.vector_db.similarity_search(question, k=k)
                    context = "\n\n".join(d.page_content for d in docs)
                except:
                    context = "\n\n".join(d["text"] for d in self.docs)
            else:
                 pass
        
        if context:
            system_msg = "You are a helpful assistant. Answer based strictly on the provided context."
            user_msg = f"Context:\n{context}\n\nQuestion: {question}"
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg}
            ]
        else:
        # --- Case 3: General Knowledge ---
            messages = [{"role": "user", "content": question}]

        return self.generate_text(messages)

    
