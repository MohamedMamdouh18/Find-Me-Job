from typing import Protocol, runtime_checkable

from ..schemas.jobs import PendingJobRequest
from ..services.run_context import RunContext


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
