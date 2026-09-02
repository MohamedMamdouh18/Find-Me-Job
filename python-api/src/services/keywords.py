import hashlib
import json
import logging
import os
from docx import Document

from .cv import docx_text
from .llm import call_llm, parse_llm_json
from .run_context import RunContext
from ..database.repositories import CVKeywordsRepository
from ..shared import CV_PATH, PARAMS_DIR

logger = logging.getLogger(__name__)


def extract_or_get_keywords(
    ctx: RunContext,
    cv_path: str = CV_PATH,
) -> tuple[str, dict[str, list[str]]]:
    """Reads CV text, hashes it (SHA-256), and retrieves or extracts {titles, skills} keywords."""
    if not os.path.isfile(cv_path):
        raise FileNotFoundError(
            f"CV file not found at {cv_path}. Please upload a .docx CV in the Settings tab."
        )

    try:
        doc = Document(cv_path)
        cv_text = docx_text(doc)
    except Exception as e:
        raise RuntimeError(
            f"Could not read CV at {cv_path} ({e}). Please ensure a valid .docx file is uploaded in the Settings tab."
        ) from e

    if not cv_text or not cv_text.strip():
        raise RuntimeError(
            f"CV file at {cv_path} contains no readable text. Please upload a .docx file with your resume content."
        )

    cv_hash = hashlib.sha256(cv_text.encode("utf-8")).hexdigest()

    repo = CVKeywordsRepository(ctx.session)
    existing = repo.get_latest()

    if existing and existing.cv_hash == cv_hash:
        ctx.emit("cv.unchanged", "CV unchanged; using cached keywords")
        try:
            keywords = json.loads(existing.keywords)
            return cv_text, keywords
        except Exception:
            logger.warning("Failed to parse cached keywords from DB; re-extracting")

    ctx.emit("cv.changed", "CV changed or keywords missing; extracting keywords via LLM")
    prompt_file = os.path.join(PARAMS_DIR, "llm_keywords_extract.txt")
    if not os.path.isfile(prompt_file):
        raise FileNotFoundError(f"Keyword extraction prompt template missing at {prompt_file}")

    with open(prompt_file, "r", encoding="utf-8") as f:
        template = f.read()

    full_prompt = f"{template}\n\nCV:\n{cv_text}"
    messages = [
        {
            "role": "system",
            "content": "You are a technical recruiter with expertise in software engineering hiring. Always respond with valid JSON only.",
        },
        {"role": "user", "content": full_prompt},
    ]

    raw_response = call_llm(messages)
    try:
        keywords = parse_llm_json(raw_response)
        # Ensure schema structure
        if not isinstance(keywords, dict):
            raise ValueError(f"Expected dict from keyword extraction, got {type(keywords)}")
        keywords.setdefault("titles", [])
        keywords.setdefault("skills", [])
    except Exception as e:
        ctx.emit(
            "keywords.failed",
            f"Failed to parse keywords response: {e}",
            level="error",
            context=raw_response[:2000],
        )
        raise

    repo.save(cv_hash, json.dumps(keywords))
    ctx.session.commit()
    ctx.emit(
        "keywords.extracted",
        f"Extracted {len(keywords.get('titles', []))} titles and {len(keywords.get('skills', []))} skills",
        context={"titles": keywords.get("titles", []), "skills": keywords.get("skills", [])},
    )

    return cv_text, keywords
