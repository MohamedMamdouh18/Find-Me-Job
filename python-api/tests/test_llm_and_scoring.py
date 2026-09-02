import json
import docx
from sqlmodel import SQLModel, Session, create_engine
from sqlmodel.pool import StaticPool

import src.database.models  # noqa: F401
from src.database.models import PendingJob, CVKeywords
from src.services.llm import parse_llm_json, repair_json
from src.services.run_context import RunContext
from src.services.keywords import extract_or_get_keywords
from src.services.scoring import score_job


def test_parse_llm_json_eight_cases():
    cases = [
        ('{"score":85,"coverLetter":"Dear Team, I am keen."}', 85),
        ('{\n  "score": 85,\n  "coverLetter": "Dear Team."\n}', 85),
        ('{"score":85,"coverLetter":"Dear Team,\nSincerely,\nM"}', 85),
        ('{\n  "score": 85,\n  "coverLetter": "Dear Team,\nSincerely"\n}', 85),
        ('{"score":70,"coverLetter":"a\tb"}', 70),
        ('{"score":90,"coverLetter":"Dear Team,\\nBest"}', 90),
        ('{"score":60,"coverLetter":"He said \\"hi\\"\nBye"}', 60),
        ('{\n "score": 55,\n "coverLetter": "Use {json} here\nEnd"\n}', 55),
    ]

    for raw, expected_score in cases:
        parsed = parse_llm_json(raw)
        assert parsed["score"] == expected_score

    # Also test with markdown code fence
    fenced = '```json\n{\n  "score": 95,\n  "coverLetter": "Excellent"\n}\n```'
    parsed_fenced = parse_llm_json(fenced)
    assert parsed_fenced["score"] == 95


def test_keywords_cached_when_hash_matches(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    # Create dummy docx
    cv_file = tmp_path / "cv.docx"
    doc = docx.Document()
    doc.add_paragraph("Python, FastAPI, SQL")
    doc.save(str(cv_file))

    import hashlib
    from src.services.cv import docx_text
    cv_text = docx_text(doc)
    cv_hash = hashlib.sha256(cv_text.encode("utf-8")).hexdigest()

    with Session(engine) as session:
        # Pre-populate cv_keywords in DB
        ck = CVKeywords(
            cv_hash=cv_hash,
            keywords=json.dumps({"titles": ["Backend Engineer"], "skills": ["Python", "FastAPI"]}),
        )
        session.add(ck)
        session.commit()

        ctx = RunContext(1, session)
        text, kw = extract_or_get_keywords(ctx, cv_path=str(cv_file))
        assert text == "Python, FastAPI, SQL"
        assert kw["titles"] == ["Backend Engineer"]
        assert kw["skills"] == ["Python", "FastAPI"]


def test_scoring_job_success(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    # Mock call_llm
    def mock_call_llm(messages, **kwargs):
        return '{\n  "score": 88,\n  "coverLetter": "Dear Team,\nI love Python."\n}'

    monkeypatch.setattr("src.services.scoring.call_llm", mock_call_llm)

    with Session(engine) as session:
        ctx = RunContext(1, session)
        job = PendingJob(
            id="job_test",
            title="Senior Python Engineer",
            company="Acme",
            location="Remote",
            applylink="https://example.com",
            description="Need 5+ years of Python.",
            website="LinkedIn",
        )
        score, letter = score_job(ctx, job, cv_text="5 years Python developer")
        assert score == 88
        assert "Dear Team,\nI love Python." in letter
