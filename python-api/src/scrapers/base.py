import html
import re
from typing import Protocol, runtime_checkable

from ..schemas.jobs import PendingJobRequest
from ..services.run_context import RunContext

# Relevance scoring, hoisted out of remoteok.py so every feed is judged the same way.
# A title the CV aims at is worth more than any single skill; a handful of skills in
# the body is enough on its own. Deliberately arithmetic and not an LLM: this runs over
# everything a feed offers, and the whole point is that it costs nothing.
TITLE_BONUS = 10
SKILL_POINTS = 3
MIN_SCORE = 6


@runtime_checkable
class Source(Protocol):
    """The contract every entry in SOURCES must satisfy.

    The pipeline owns persistence, blocklisting and per-source failure isolation, so a
    source only fetches and returns candidates: it must not write to the database.

    `keywords` carries the CV-derived titles and skills. A source may ignore it —
    LinkedIn reads params/linkedin_searches.txt instead — but it is always passed, so
    it is a required parameter rather than an optional one.
    """

    def __call__(self, ctx: RunContext, keywords: dict) -> list[PendingJobRequest]: ...


def clean_description(text: str, unescape_first: bool = False) -> str:
    """Strips tags, unescapes entities, removes spam cues, and collapses whitespace.

    The order is a per-source decision, not a detail. RemoteOK serves real markup, so
    tags are stripped first: unescaping first would turn an escaped "&lt;div&gt;" into a
    real tag and the strip would then eat the text up to the next ">". Greenhouse serves
    the opposite — its `content` is entity-escaped HTML — so stripping first finds no
    tags at all and leaves literal markup in the description, which is then paid for
    twice, in the scoring prompt and in the cover letter prompt.
    """
    if not text:
        return ""
    if unescape_first:
        text = html.unescape(text)
        text = re.sub(r"<[^>]*>", " ", text)
    else:
        text = re.sub(r"<[^>]*>", " ", text)
        text = html.unescape(text)
    text = text.replace("\xc2", "").replace("Â", "")
    text = re.split(r"please mention the word", text, flags=re.IGNORECASE)[0]
    text = re.sub(r"\s+", " ", text).strip()
    return text


def word_pattern(term: str) -> re.Pattern:
    """Case-insensitive match delimited by whitespace, punctuation or string boundary,
    so "go" does not match "goalkeeper" and "r" does not match every word."""
    escaped = re.escape(term)
    return re.compile(
        r"(?:^|[\s,;/()\[\]|•·–—-])" + escaped + r"(?:$|[\s,;/()\[\]|•·–—-])",
        re.IGNORECASE,
    )


def relevance(job: PendingJobRequest, keywords: dict) -> int:
    titles = keywords.get("titles") or []
    skills = keywords.get("skills") or []

    score = 0
    haystack = f"{job.title} {job.description}"
    if any(word_pattern(title).search(job.title) for title in titles if title):
        score += TITLE_BONUS
    for skill in skills:
        if skill and word_pattern(skill).search(haystack):
            score += SKILL_POINTS
    return score


def prefilter(jobs: list[PendingJobRequest], keywords: dict) -> list[PendingJobRequest]:
    """Feed jobs worth queueing, best first.

    A feed carries the whole world, so this is what stops the queue filling with roles
    the user would never open — each of which would otherwise cost a scoring wait and an
    LLM call. Company jobs do not come through here: the user named that employer, so
    relevance is already established and a sideways role their keywords miss is exactly
    the job they want to see.
    """
    scored = [(relevance(job, keywords), job) for job in jobs]
    kept = [pair for pair in scored if pair[0] >= MIN_SCORE]
    kept.sort(key=lambda pair: pair[0], reverse=True)
    return [job for _, job in kept]
