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
    assert "Do not require the document to state an explicit ranking" in system_prompt
    assert "listed skills supported by work or projects" in system_prompt
    assert "Never invent facts, skills, experience, numbers, or events" in system_prompt
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


def test_general_grounding_prompt_allows_supported_synthesis_for_strengths_question(tmp_path):
    text_file = tmp_path / "cv.txt"
    text_file.write_text(
        "Skills: Python, SQL, Docker. Built Python data pipelines and SQL dashboards. "
        "Deployed Docker services for production analytics.",
        encoding="utf-8",
    )
    agent = RAGCore(upload_dir=str(tmp_path / "uploads"), db_path=str(tmp_path / "rag.sqlite3"))
    agent.use_vector_db = False
    document_id = agent.create_ingestion_job(text_file.name)
    agent.ingest_file(document_id, str(text_file))
    captured = {}

    def fake_generate(messages, image=None, max_new_tokens=1024):
        captured["messages"] = messages
        return "The strongest areas appear to be Python, SQL, and Docker, based on the described projects."

    agent.generate_text = fake_generate
    result = agent.answer_with_sources("What are the strongest technical areas in this CV?")

    system_prompt = captured["messages"][0]["content"]
    assert "synthesize supported conclusions about strengths, suitability, comparisons" in system_prompt
    assert "Never invent facts, skills, experience, numbers, or events" in system_prompt
    assert "Python data pipelines" in captured["messages"][1]["content"]
    assert result["answer"].startswith("The strongest areas")
    assert result["sources"][0]["filename"] == "cv.txt"
    assert result["sources"][0]["page_number"] == 1


def test_exact_strongest_areas_query_uses_concise_grounded_answer_policy(tmp_path):
    text_file = tmp_path / "cv.txt"
    text_file.write_text(
        "Skills: Python, SQL, Docker. Built Python data pipelines and SQL dashboards. "
        "Deployed Docker services for production analytics.",
        encoding="utf-8",
    )
    agent = RAGCore(upload_dir=str(tmp_path / "uploads"), db_path=str(tmp_path / "rag.sqlite3"))
    agent.use_vector_db = False
    document_id = agent.create_ingestion_job(text_file.name)
    agent.ingest_file(document_id, str(text_file))
    captured = {}

    def fake_generate(messages, image=None, max_new_tokens=1024):
        captured["messages"] = messages
        captured["max_new_tokens"] = max_new_tokens
        return "Python, SQL, and Docker are the strongest areas, supported by the candidate's projects."

    agent.generate_text = fake_generate
    result = agent.answer_with_sources("What are the 3 strongest technical areas in this CV?")

    policy = captured["messages"][0]["content"]
    assert "Keep simple answers to 1-5 lines" in policy
    assert "never reveal chain-of-thought" in policy
    assert "Deduplicate facts" in policy
    assert "Built Python data pipelines" in captured["messages"][1]["content"]
    assert captured["max_new_tokens"] == 2048
    assert result["answer"].startswith("Python, SQL, and Docker")
    assert result["sources"][0]["page_number"] == 1


def test_explicit_detail_request_gets_extended_output_budget(tmp_path):
    text_file = tmp_path / "profile.txt"
    text_file.write_text("The candidate uses Python for data analysis.", encoding="utf-8")
    agent = RAGCore(upload_dir=str(tmp_path / "uploads"), db_path=str(tmp_path / "rag.sqlite3"))
    agent.use_vector_db = False
    document_id = agent.create_ingestion_job(text_file.name)
    agent.ingest_file(document_id, str(text_file))
    captured = {}

    def fake_generate(messages, image=None, max_new_tokens=1024):
        captured["messages"] = messages
        captured["max_new_tokens"] = max_new_tokens
        return "Detailed answer."

    agent.generate_text = fake_generate
    agent.answer_with_sources("Explain in detail how the candidate uses Python.")

    assert captured["max_new_tokens"] == 4096
    assert "Give longer answers only when explicitly requested" in captured["messages"][0]["content"]


def test_direct_factual_question_keeps_same_grounding_behavior(tmp_path):
    text_file = tmp_path / "profile.txt"
    text_file.write_text("The candidate uses Python for data analysis.", encoding="utf-8")
    agent = RAGCore(upload_dir=str(tmp_path / "uploads"), db_path=str(tmp_path / "rag.sqlite3"))
    agent.use_vector_db = False
    document_id = agent.create_ingestion_job(text_file.name)
    agent.ingest_file(document_id, str(text_file))
    captured = {}

    def fake_generate(messages, image=None, max_new_tokens=1024):
        captured["messages"] = messages
        return "The candidate uses Python for data analysis."

    agent.generate_text = fake_generate
    result = agent.answer_with_sources("What language does the candidate use?")

    assert result["answer"] == "The candidate uses Python for data analysis."
    assert "only the supplied context" in captured["messages"][0]["content"]
    assert "Python for data analysis" in captured["messages"][1]["content"]
    assert result["sources"][0]["page_number"] == 1


def test_exact_cv_ranking_query_keeps_retrieved_skill_context_within_limit(tmp_path):
    agent = RAGCore(upload_dir=str(tmp_path / "uploads"), db_path=str(tmp_path / "rag.sqlite3"))
    agent.use_vector_db = False
    matches = [
        {
            "document_id": "cv",
            "source": "cv.txt",
            "page_number": index,
            "text": f"Skills section {index}: Python, SQL, Docker, React. " + "evidence " * 2_000,
        }
        for index in range(1, 7)
    ]
    captured = {}

    agent._records = lambda: matches
    agent.retrieve = lambda question, k=5: matches[:k]

    def fake_generate(messages, image=None, max_new_tokens=1024):
        captured["messages"] = messages
        return "ranking"

    agent.generate_text = fake_generate

    result = agent.answer_with_sources("List the 6 most important skills for a CV holder.", k=1)

    prompt = captured["messages"][1]["content"]
    assert result["answer"] == "ranking"
    assert "Skills section 1: Python, SQL, Docker, React." in prompt
    assert len(prompt) <= 25_000
    assert len(RAGCore._context_from_matches(matches)) <= 24_000
