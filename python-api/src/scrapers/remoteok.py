import html
import logging
import re

from ..schemas.jobs import PendingJobRequest
from ..services.http import get
from ..services.run_context import RunContext

logger = logging.getLogger(__name__)

TITLE_BONUS = 10
SKILL_POINTS = 3
MIN_SCORE = 6


def word_pattern(term: str) -> re.Pattern:
    """Builds a case-insensitive regex pattern delimited by whitespace, punctuation, or string boundary."""
    escaped = re.escape(term)
    return re.compile(
        r"(?:^|[\s,;/()\[\]|•·–—-])" + escaped + r"(?:$|[\s,;/()\[\]|•·–—-])",
        re.IGNORECASE,
    )


def clean_description(text: str) -> str:
    """Strips tags, unescapes entities, removes spam cues, and collapses whitespace."""
    if not text:
        return ""
    # Strip tags before unescaping: unescaping first turns escaped markup such as
    # "&lt;div&gt;" into a real tag, which the tag strip then deletes along with any
    # text up to the next ">".
    text = re.sub(r"<[^>]*>", " ", text)
    text = html.unescape(text)
    text = text.replace("\xc2", "").replace("Â", "")
    text = re.split(r"please mention the word", text, flags=re.IGNORECASE)[0]
    text = re.sub(r"\s+", " ", text).strip()
    return text


def filter_and_score_remoteok_jobs(
    raw_items: list[dict],
    keywords: dict[str, list[str]],
) -> list[PendingJobRequest]:
    """Scores RemoteOK items against candidate keywords and converts matches to PendingJobRequest."""
    if not raw_items:
        return []

    # Drop element 0 (legal notice)
    jobs_data = raw_items[1:] if len(raw_items) > 1 else []

    titles = keywords.get("titles", [])
    skills = keywords.get("skills", [])

    title_patterns = [word_pattern(t) for t in titles if t]
    skill_patterns = [word_pattern(s) for s in skills if s]

    scored_jobs = []

    for item in jobs_data:
        if not isinstance(item, dict):
            continue
        job_id = item.get("id")
        if not job_id:
            continue

        position = item.get("position") or ""
        tags = item.get("tags") or []
        raw_desc = item.get("description") or (", ".join(tags) if isinstance(tags, list) else "")
        desc = clean_description(raw_desc)
        full_text = f"{position} {desc}"

        score = 0
        if any(p.search(full_text) for p in title_patterns):
            score += TITLE_BONUS

        for p in skill_patterns:
            if p.search(full_text):
                score += SKILL_POINTS

        if score >= MIN_SCORE:
            scored_jobs.append((score, item, desc))

    # Sort descending by score
    scored_jobs.sort(key=lambda x: x[0], reverse=True)

    results = []
    for score, item, desc in scored_jobs:
        results.append(
            PendingJobRequest(
                id=f"remoteok_{item['id']}",
                title=item.get("position", ""),
                company=item.get("company", ""),
                location="Remote",
                applylink=item.get("url", ""),
                description=desc,
                website="RemoteOK",
                easy_apply=False,
            )
        )

    return results


def fetch(ctx: RunContext, keywords: dict | None = None) -> list[PendingJobRequest]:
    """Fetches and filters remote jobs from RemoteOK API."""
    ctx.emit("scrape.remoteok.start", "Fetching RemoteOK jobs API")
    url = "https://remoteok.com/api"
    try:
        res = get(url, timeout=30.0, tries=3, wait=5.0, headers={"User-Agent": "Mozilla/5.0"})
        data = res.json()
        if not isinstance(data, list):
            logger.warning(f"Unexpected RemoteOK response type: {type(data)}")
            return []
        
        kw = keywords or {"titles": [], "skills": []}
        jobs = filter_and_score_remoteok_jobs(data, kw)
        ctx.emit(
            "scrape.remoteok.done",
            f"Finished RemoteOK scrape. Kept {len(jobs)} jobs",
            context={"found": len(jobs)},
        )
        return jobs
    except Exception as e:
        logger.warning(f"RemoteOK scrape failed: {e}")
        ctx.emit("scrape.remoteok.failed", f"RemoteOK scrape failed: {e}", level="error")
        return []
