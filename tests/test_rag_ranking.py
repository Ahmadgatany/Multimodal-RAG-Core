from backend.rag_core import RAGCore


def test_cv_ranking_request_uses_evidence_based_inference_prompt(tmp_path):
    text_file = tmp_path / "cv.txt"
    text_file.write_text(
        "Skills: Python, SQL, Docker, React, Excel, Git. "
        "Experience: Built Python data pipelines and SQL dashboards. "
        "Projects: Deployed Docker services and a React analytics dashboard.",
        encoding="utf-8",
    )
    agent = RAGCore(upload_dir=str(tmp_path / "uploads"), db_path=str(tmp_path / "rag.sqlite3"))
    agent.use_vector_db = False
    document_id = agent.create_ingestion_job(text_file.name)
    agent.ingest_file(document_id, str(text_file))
    captured = {}
    original_retrieve = agent.retrieve

    def tracked_retrieve(question, k=5):
        captured["retrieval_k"] = k
        return original_retrieve(question, k)

    agent.retrieve = tracked_retrieve

    def fake_generate(messages, image=None, max_new_tokens=1024):
        captured["messages"] = messages
        return "Inferred ranking: Python, SQL, Docker, React, Git, Excel"

    agent.generate_text = fake_generate
    result = agent.answer_with_sources("List the 6 most important skills for a CV holder.", k=1)

    system_prompt = captured["messages"][0]["content"]
    assert result["answer"].startswith("Inferred ranking")
    assert "reasonable evidence-based inference" in system_prompt
    assert "prioritize clearly listed skills" in system_prompt
    assert "Do not invent facts, skills, or accomplishments" in system_prompt
    assert "Python data pipelines" in captured["messages"][1]["content"]
    assert captured["retrieval_k"] == 6
    assert RAGCore._requested_item_count("List the 6 most important skills") == 6


def test_non_ranking_question_does_not_add_ranking_instruction(tmp_path):
    agent = RAGCore(upload_dir=str(tmp_path / "uploads"), db_path=str(tmp_path / "rag.sqlite3"))
    agent.use_vector_db = False
    document_id = agent.create_ingestion_job("profile.txt")
    profile = tmp_path / "profile.txt"
    profile.write_text("The candidate uses Python for data analysis.", encoding="utf-8")
    agent.ingest_file(document_id, str(profile))
    captured = {}

    def fake_generate(messages, image=None, max_new_tokens=1024):
        captured["system"] = messages[0]["content"]
        return "The candidate uses Python for data analysis."

    agent.generate_text = fake_generate
    agent.answer_with_sources("What language does the candidate use?")

    assert "reasonable evidence-based inference" not in captured["system"]
