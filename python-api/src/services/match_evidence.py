"""Which of the CV's skills a posting actually asks for.

The scorer returns `{score, coverLetter}` and nothing else, so the model's own
reasoning is not available to show. What is available is the overlap between the
skills extracted from the CV and the text of the posting. That is a literal
keyword match, never the model's rationale, and the UI labels it as such.
"""

import json
import re

MAX_MATCHED = 12


def parse_keywords(raw: str | None) -> tuple[list[str], list[str]]:
    """`cv_keywords.keywords` holds the extractor's raw JSON reply."""
    if not raw:
        return [], []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return [], []
    titles = [str(t).strip() for t in parsed.get("titles", []) if str(t).strip()]
    skills = [str(s).strip() for s in parsed.get("skills", []) if str(s).strip()]
    return titles, skills


def _pattern(skill: str) -> re.Pattern:
    """Boundaries only where the edge is a word character, so "C++", ".NET" and
    "Node.js" still match — \\b next to punctuation asserts the opposite thing."""
    body = re.escape(skill)
    left = r"\b" if skill[:1].isalnum() else ""
    right = r"\b" if skill[-1:].isalnum() else ""
    return re.compile(left + body + right, re.IGNORECASE)


def matched_skills(description: str | None, skills: list[str]) -> list[str]:
    if not description or not skills:
        return []
    text = description
    return [s for s in skills if _pattern(s).search(text)][:MAX_MATCHED]


def evidence(description: str | None, skills: list[str]) -> dict:
    hits = matched_skills(description, skills)
    hit_set = {h.lower() for h in hits}
    return {
        "matched": hits,
        "missing": [s for s in skills if s.lower() not in hit_set][:MAX_MATCHED],
        "skills_known": len(skills),
    }
