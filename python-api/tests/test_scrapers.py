import json
import os
from src.scrapers.linkedin import (
    build_linkedin_search_url,
    parse_search_links,
    parse_job_page,
)
from src.scrapers.remoteok import (
    clean_description,
    word_pattern,
    filter_and_score_remoteok_jobs,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def test_build_linkedin_search_url():
    params = {
        "Keyword": "Software Engineer",
        "Location": "Egypt",
        "Experience Level": "Entry level, Associate, Mid-Senior level",
        "Remote": "Remote, Hybrid, On-Site",
        "Job Type": "Full-time",
        "Last Posted": "r604800",
        "Easy Apply": "",
    }
    url = build_linkedin_search_url(params)
    expected = (
        "https://www.linkedin.com/jobs/search/?"
        "f_TPR=r604800"
        "&keywords=Software%20Engineer"
        "&location=Egypt"
        "&f_E=2,3,4"
        "&f_WT=2,3,1"
        "&f_JT=F"
    )
    assert url == expected


def test_parse_linkedin_search_links_fixture():
    search_file = os.path.join(FIXTURES_DIR, "linkedin_search.html")
    with open(search_file, "r", encoding="utf-8") as f:
        html = f.read()

    links = parse_search_links(html)
    assert len(links) > 0
    # Every extracted link must have a valid digits ID
    for url, link_id in links:
        assert link_id.isdigit()
        assert "undefined" not in link_id

    # Test that unparseable URLs are discarded
    bad_html = '<ul class="jobs-search__results-list"><li><a class="base-card__full-link" href="https://linkedin.com/jobs/view/no-job-id-here">link</a></li></ul>'
    assert parse_search_links(bad_html) == []


def test_parse_linkedin_job_page_fixture():
    job_file = os.path.join(FIXTURES_DIR, "linkedin_job.html")
    with open(job_file, "r", encoding="utf-8") as f:
        html = f.read()

    job = parse_job_page(html, "4438676223")
    assert job is not None
    assert "Deloitte" in job.company
    assert len(job.title) > 0
    assert len(job.description) > 0
    assert job.id.startswith("linkedin_")
    assert job.website == "LinkedIn"


def test_remoteok_filter_and_scoring_fixture():
    api_file = os.path.join(FIXTURES_DIR, "remoteok_api.json")
    with open(api_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Element 0 is legal notice
    assert "legal" in str(data[0]).lower() or "terms" in str(data[0]).lower() or "notice" in str(data[0]).lower()

    keywords = {
        "titles": ["Technician", "Engineer", "Specialist"],
        "skills": ["technical", "dev", "node"],
    }

    filtered = filter_and_score_remoteok_jobs(data, keywords)
    assert len(filtered) > 0

    # Every item must have Remote location and remoteok_ id prefix
    for job in filtered:
        assert job.id.startswith("remoteok_")
        assert job.location == "Remote"
        assert job.website == "RemoteOK"

    # Test with no matching keywords => returns empty
    empty_kw = {"titles": ["NonExistentTitleXYZ123"], "skills": ["NonExistentSkillXYZ123"]}
    no_matches = filter_and_score_remoteok_jobs(data, empty_kw)
    assert len(no_matches) == 0


def test_clean_description():
    raw = "<p>Join our team! &amp;&nbsp;ÂPlease mention the word CANDIDATE when applying.</p>"
    cleaned = clean_description(raw)
    assert "Join our team! &" in cleaned
    assert "Â" not in cleaned
    assert "Please mention the word" not in cleaned


def test_remoteok_drops_the_legal_notice_element():
    """RemoteOK returns a legal notice as element 0. Keeping it would turn the notice
    into a job posting whenever it happens to match a keyword."""
    from src.scrapers.remoteok import filter_and_score_remoteok_jobs

    legal = {
        "id": "legal-notice",
        "legal": "Please note RemoteOK is a job board",
        "position": "Python Engineer",
        "company": "Notice",
        "description": "Python Django Docker AWS",
        "url": "https://remoteok.com/legal",
    }
    real = {
        "id": "999",
        "position": "Python Engineer",
        "company": "Acme",
        "description": "Python Django Docker AWS",
        "url": "https://remoteok.com/l/999",
    }
    keywords = {"titles": ["Python Engineer"], "skills": ["Python", "Django", "Docker"]}

    out = filter_and_score_remoteok_jobs([legal, real], keywords)
    ids = [j.id for j in out]
    assert ids == ["remoteok_999"], f"legal notice leaked through: {ids}"


def test_linkedin_easy_apply_is_true_only_without_the_offsite_icon():
    """easy_apply is inverted: the offsite-apply icon means the job is NOT easy apply."""
    from src.scrapers.linkedin import parse_job_page

    body = (
        '<div><h1>Engineer</h1><span><a>Acme</a></span>'
        '<div class="description__text description__text--rich">Build things</div>'
        '<a data-item-type="semaphore" data-semaphore-content-urn="urn:li:jobPosting:4242"></a>'
        "</div>"
    )
    easy = parse_job_page(f"<html>{body}</html>", "4242")
    offsite = parse_job_page(
        f'<html>{body}<svg class="apply-button__offsite-apply-icon-svg"></svg></html>', "4242"
    )

    assert easy is not None and offsite is not None
    assert easy.easy_apply is True, "no offsite icon should mean easy apply"
    assert offsite.easy_apply is False, "offsite icon present should mean NOT easy apply"


def test_clean_description_strips_tags_before_unescaping():
    """Unescaping first would turn "&lt;script&gt;" into a real tag, and the tag strip
    would then delete it along with any text up to the next ">"."""
    from src.scrapers.remoteok import clean_description

    out = clean_description("<p>Use &lt;script&gt; tags and R&amp;D skills</p>")
    assert "script" in out, f"escaped markup was swallowed: {out!r}"
    assert "R&D" in out
