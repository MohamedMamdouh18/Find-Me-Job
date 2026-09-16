"""Parsers for the company boards and the new feeds, over recorded payloads.

Same shape as test_scrapers.py: a fixture captured once from the live endpoint, trimmed
to a couple of jobs, parsed offline. The parsers are pure — they take a payload and the
company row's label, and return PendingJobRequest — so nothing here touches the network.

The assertions that matter are the ones a wrong mapping would silently pass: the company
comes from the row rather than the payload, the description carries no markup, and a
response that is not the expected shape yields zero jobs instead of raising.
"""

import json
import os

import pytest

from src.scrapers.boards import parse_ashby, parse_greenhouse, parse_lever
from src.scrapers.himalayas import parse_himalayas
from src.scrapers.weworkremotely import parse_wwr

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _json(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def _text(name):
    with open(os.path.join(FIXTURES_DIR, name), encoding="utf-8") as f:
        return f.read()


# ── company boards ───────────────────────────────────────────────────────────


def test_greenhouse_maps_every_field():
    jobs = parse_greenhouse(_json("greenhouse_board.json"), token="stripe", company="Stripe")

    assert len(jobs) == 2
    job = jobs[0]
    assert job.id.startswith("greenhouse_stripe_")
    assert job.title
    assert job.company == "Stripe"
    assert job.location
    assert job.applylink.startswith("https://")
    assert job.website == "Greenhouse"
    assert job.easy_apply is False


def test_greenhouse_descriptions_carry_no_markup():
    """content arrives entity-escaped, so the cleaner has to unescape before it strips.
    The wrong order leaves literal <h2> in the text, paid for twice in the prompts."""
    job = parse_greenhouse(_json("greenhouse_board.json"), token="stripe", company="Stripe")[0]

    assert "&lt;" not in job.description
    assert "<h2" not in job.description
    assert "<p>" not in job.description
    assert len(job.description) > 200


def test_lever_description_uses_all_three_keys():
    """descriptionPlain alone is about a third of the posting; the rest is in lists[]
    and additionalPlain."""
    payload = _json("lever_postings.json")
    jobs = parse_lever(payload, token="palantir", company="Palantir")

    assert len(jobs) == 2
    # Matched by id, not by position: parsers return newest first, so the order no longer
    # follows the payload's.
    by_id = {job.id: job for job in jobs}
    for row in payload:
        job = by_id[f"lever_palantir_{row['id']}"]
        assert job.company == "Palantir"
        assert job.website == "Lever"
        assert len(job.description) > len(row["descriptionPlain"])
        for entry in row.get("lists", []):
            assert entry["text"] in job.description


def test_ashby_maps_every_field():
    jobs = parse_ashby(_json("ashby_board.json"), token="ramp", company="Ramp")

    assert len(jobs) == 2
    job = jobs[0]
    assert job.id.startswith("ashby_ramp_")
    assert job.company == "Ramp"
    assert job.website == "Ashby"
    assert job.applylink.startswith("https://")
    assert len(job.description) > 200


def test_the_company_name_comes_from_the_row_not_the_payload():
    """Lever and Ashby carry no company at all, and deriving one from a display name is
    how you get jobs.ashbyhq.com/scaleai for "Scale AI"."""
    for parse, fixture, token in (
        (parse_greenhouse, "greenhouse_board.json", "stripe"),
        (parse_lever, "lever_postings.json", "palantir"),
        (parse_ashby, "ashby_board.json", "ramp"),
    ):
        jobs = parse(_json(fixture), token=token, company="Renamed Ltd")
        assert {job.company for job in jobs} == {"Renamed Ltd"}


@pytest.mark.parametrize(
    "parse,payload",
    [
        (parse_greenhouse, {"not": "a board"}),
        (parse_greenhouse, []),
        (parse_lever, {"not": "a list"}),
        (parse_ashby, {"jobs": "not a list"}),
        (parse_ashby, None),
    ],
)
def test_a_payload_of_the_wrong_shape_yields_no_jobs(parse, payload):
    """BambooHR answers an unknown token with HTTP 200 and its own marketing page, and it
    will not be the only one. A board is healthy when it parses, never because of a status
    code — and an unparseable response is a dead token, not a crash."""
    assert parse(payload, token="whoever", company="Whoever") == []


# ── feeds ────────────────────────────────────────────────────────────────────


def test_himalayas_maps_every_field():
    jobs = parse_himalayas(_json("himalayas_page.json"))

    assert len(jobs) == 2
    job = jobs[0]
    assert job.id.startswith("himalayas_")
    assert job.company  # the feed carries companyName, unlike the boards
    assert job.title
    assert job.applylink.startswith("https://")
    assert job.website == "Himalayas"
    assert len(job.description) > 200


def test_wwr_splits_the_company_out_of_the_title():
    """The feed puts "Company: Role" in one element and has no company field."""
    jobs = parse_wwr(_text("wwr_feed.rss"))

    assert len(jobs) == 2
    job = jobs[0]
    assert job.id.startswith("wwr_")
    assert job.company
    assert ":" not in job.company
    assert job.title
    assert not job.title.startswith(job.company)
    assert job.website == "We Work Remotely"


def test_wwr_descriptions_carry_no_markup():
    job = parse_wwr(_text("wwr_feed.rss"))[0]

    assert "<p>" not in job.description
    assert "&lt;" not in job.description


@pytest.mark.parametrize("payload", [{"jobs": "not a list"}, {}, None])
def test_a_broken_feed_yields_no_jobs(payload):
    assert parse_himalayas(payload) == []


def test_a_broken_rss_yields_no_jobs():
    assert parse_wwr("<html>not a feed</html>") == []


def test_every_parser_returns_newest_first():
    """The intake cap truncates, so the order a parser returns its jobs in decides which
    ones get queued. Lever hands its postings over oldest-first, which without this means
    a company with more openings than the cap gets its stalest requisitions queued and its
    new ones dropped, every night, silently."""
    payload = _json("lever_postings.json")
    oldest_first = [row["createdAt"] for row in payload]
    assert oldest_first != sorted(oldest_first, reverse=True), (
        "this fixture no longer exercises the case — recapture one that is out of order"
    )

    jobs = parse_lever(payload, token="palantir", company="Palantir")
    newest = max(payload, key=lambda row: row["createdAt"])
    assert jobs[0].id.endswith(str(newest["id"]))

    himalayas = _json("himalayas_page.json")
    parsed = parse_himalayas(himalayas)
    freshest = max(himalayas["jobs"], key=lambda row: row["pubDate"])
    assert parsed[0].id.endswith(str(freshest["guid"]))


# ── We Work Remotely categories ──────────────────────────────────────────────


def test_only_known_categories_are_accepted():
    """The slug goes straight into a URL, and a typo would be a 404 reported as an empty
    category — which reads as "nothing posted this week" rather than "wrong setting"."""
    from src.services import settings

    assert settings.parse_setting("WWR_CATEGORIES", "remote-programming-jobs") == [
        "remote-programming-jobs"
    ]
    assert settings.parse_setting("WWR_CATEGORIES", "") == []
    with pytest.raises(ValueError):
        settings.parse_setting("WWR_CATEGORIES", "remote-underwater-basket-weaving")
    with pytest.raises(ValueError):
        settings.parse_setting(
            "WWR_CATEGORIES",
            ",".join(settings.WWR_CATEGORY_SLUGS),  # more than five requests
        )


def test_a_challenge_page_is_not_an_empty_category():
    """We Work Remotely answers rapid requests with an interstitial: HTTP 200, no items.
    Counting that as zero jobs is the silent zero this phase exists to avoid."""
    from src.scrapers.weworkremotely import _looks_challenged

    assert _looks_challenged("<html><head><title>Just a moment...</title></head></html>")
    assert not _looks_challenged(_text("wwr_feed.rss"))
    # An empty but genuine feed is not a challenge — it really has nothing in it.
    assert not _looks_challenged('<?xml version="1.0"?><rss version="2.0"><channel/></rss>')
