"""How two records are recognised as the same company, or the same job.

Identity within one source is its own id and that is exact. Across sources it is not:
the board posting and the feed's syndication of it share nothing but the words. This is
the normalisation both cases lean on, and it is deliberately one helper — the blocklist
needs it too, because it is exact-match today and therefore blocks "Acme" while "Acme,
Inc." keeps arriving every night.
"""

import hashlib
import re

# Dropped from the end of a company name before matching. Kept deliberately short: these
# are legal-form suffixes, not words that distinguish one employer from another.
LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "ltd",
    "limited",
    "llc",
    "llp",
    "plc",
    "gmbh",
    "ag",
    "bv",
    "nv",
    "oy",
    "ab",
    "corp",
    "corporation",
    "co",
    "company",
    "group",
    "holdings",
}


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace. Display keeps the raw value;
    only matching sees this."""
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalise_company(name: str) -> str:
    """As above, then without the legal suffix. "Acme, Inc." and "ACME" are one company."""
    words = normalise(name).split()
    while words and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


def fingerprint(company: str, title: str, location: str) -> str:
    """The cross-source identity of a role.

    Two genuinely different requisitions with the same title at the same company and
    location collapse into one. That is the accepted trade: a duplicated card is a daily
    annoyance across every source, while a lost near-identical requisition is rare and
    still reachable from the company's own board.
    """
    parts = f"{normalise_company(company)}::{normalise(title)}::{normalise(location)}"
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()
