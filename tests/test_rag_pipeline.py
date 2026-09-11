from backend.rag_core import RAGCore
from PIL import Image


def test_ingestion_persists_metadata_and_exposes_retrieval(tmp_path):
    text_file = tmp_path / "architecture.txt"
    text_file.write_text("RAG combines retrieval with grounded answer generation.", encoding="utf-8")

    agent = RAGCore(upload_dir=str(tmp_path / "uploads"), db_path=str(tmp_path / "rag.sqlite3"))
    agent.use_vector_db = False  # Keep this unit test offline and deterministic.
    document_id = agent.create_ingestion_job(text_file.name)
    agent.ingest_file(document_id, str(text_file))

    assert agent.get_job(document_id)["status"] == "ready"
    matches = agent.retrieve("What does RAG combine?", k=1)
    assert matches[0]["document_id"] == document_id
    assert matches[0]["page_number"] == 1
    assert "retrieval" in matches[0]["text"]


def test_follow_up_question_reuses_uploaded_image(tmp_path):
    image_file = tmp_path / "invoice.jpeg"
    Image.new("RGB", (20, 20), "white").save(image_file)

    agent = RAGCore(upload_dir=str(tmp_path / "uploads"), db_path=str(tmp_path / "rag.sqlite3"))
    agent.use_vector_db = False
    document_id = agent.create_ingestion_job(image_file.name)
    agent.ingest_file(document_id, str(image_file))
    captured = {}

    def fake_generate(messages, image=None, max_new_tokens=1024):
        captured["image"] = image
        return "invoice answer"

    agent.generate_text = fake_generate
    result = agent.answer_with_sources("Who is the invoice from and to?")

    assert result["answer"] == "invoice answer"
    assert captured["image"] is not None
