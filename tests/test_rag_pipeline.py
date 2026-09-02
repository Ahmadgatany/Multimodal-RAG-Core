from backend.rag_core import RAGCore


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
