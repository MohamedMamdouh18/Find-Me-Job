import logging
import os

from . import settings
from .llm import call_llm, parse_llm_json
from .run_context import RunContext
from ..database.models import PendingJob
from ..shared import PARAMS_DIR, now

logger = logging.getLogger(__name__)


def score_job(
    ctx: RunContext,
    job: PendingJob,
    cv_text: str,
) -> tuple[int, str]:
    """Scores a single job against the candidate's CV and generates a cover letter if fit."""
    prompt_file = os.path.join(PARAMS_DIR, "llm_scoring.txt")
    if not os.path.isfile(prompt_file):
        raise FileNotFoundError(f"Scoring prompt template missing at {prompt_file}")

    with open(prompt_file, "r", encoding="utf-8") as f:
        template = f.read()

    today_str = now().strftime("%A, %B %d, %Y")
    filtering_score = settings.get_filtering_score()
    system_prompt = template.replace("{today}", today_str).replace(
        "{filtering_score}", str(filtering_score)
    )

    user_content = f"Job Description:\n{job.description}\n\nResume:\n{cv_text}"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]

    raw_response = call_llm(messages)
    try:
        parsed = parse_llm_json(raw_response)
        score = int(parsed.get("score", 0))
        cover_letter = str(parsed.get("coverLetter") or "")
        return score, cover_letter
    except Exception as e:
        ctx.emit(
            "score.failed",
            f"Failed to parse score for job {job.id}: {e}",
            level="error",
            context=raw_response[:2000],
        )
        raise
