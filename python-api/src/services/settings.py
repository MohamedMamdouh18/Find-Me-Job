import os


def get_llm_url() -> str:
    return (
        os.getenv("LLM_URL")
        or "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    )


def get_llm_model() -> str:
    return os.getenv("LLM_MODEL") or "gemini-2.5-flash"


def get_llm_api_key() -> str:
    return os.getenv("LLM_API_KEY") or ""


def get_filtering_score() -> int:
    return int(os.getenv("FILTERING_SCORE") or 60)


def get_auto_email() -> bool:
    return bool(os.getenv("AUTO_EMAIL"))


def get_scoring_delay() -> int:
    return int(os.getenv("SCORING_DELAY_SECONDS") or 20)


def get_delete_old_jobs_days() -> int:
    return int(os.getenv("DELETE_OLD_JOBS_DAYS") or 60)


def get_sender_name() -> str:
    return os.getenv("SENDER_NAME") or ""
