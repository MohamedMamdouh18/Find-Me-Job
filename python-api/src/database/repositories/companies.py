from sqlmodel import Session, select

from ..models.starred_company import StarredCompany
from ...shared import now

# Two empty fetches in a row is a broken row, not bad luck: a board with a rotted token
# and a page that has been redesigned both look exactly like this, and retrying either
# every night forever is how a source comes to lie about its own health.
EMPTY_FETCHES_BEFORE_OFF = 2


class CompanyRepository:
    """The company list, addressed as companies rather than as starred rows.

    The table name is historical — see the model — and this repository is the vocabulary
    the rest of Phase 2 speaks. StarredCompanyRepository still serves the starring UI.
    """

    def __init__(self, session: Session):
        self.session = session

    def get(self, company_id: int) -> StarredCompany | None:
        return self.session.get(StarredCompany, company_id)

    def get_all(self) -> list[StarredCompany]:
        return list(
            self.session.exec(
                select(StarredCompany).order_by(StarredCompany.company_name)
            ).all()
        )

    def in_workflow(self) -> list[StarredCompany]:
        """The rows the nightly walk fetches. A row is only here because the user turned
        it on, and the switch refuses to turn on for a company we cannot read."""
        return list(
            self.session.exec(
                select(StarredCompany)
                .where(StarredCompany.in_workflow.is_(True))
                .order_by(StarredCompany.company_name)
            ).all()
        )

    def awaiting_detection(self) -> list[StarredCompany]:
        """Rows with a careers URL whose verdict has not been worked out yet."""
        return list(
            self.session.exec(
                select(StarredCompany)
                .where(StarredCompany.fetch_method == "unknown")
                .where(StarredCompany.careers_url.is_not(None))
            ).all()
        )

    def set_detection(self, company: StarredCompany, verdict: dict) -> StarredCompany:
        company.fetch_method = verdict["fetch_method"]
        company.ats = verdict.get("ats")
        company.ats_token = verdict.get("ats_token")
        company.fetch_note = verdict.get("fetch_note")
        if company.fetch_method == "unreadable":
            # A row we cannot read cannot be in the workflow: leaving the switch on would
            # contribute a silent zero to every run from now on.
            company.in_workflow = False
        self.session.add(company)
        return company

    def record_fetch(self, company: StarredCompany, job_count: int) -> StarredCompany:
        company.last_scraped_at = now()
        company.last_job_count = job_count
        company.consecutive_empty = 0 if job_count else company.consecutive_empty + 1
        if company.consecutive_empty >= EMPTY_FETCHES_BEFORE_OFF:
            company.fetch_method = "unreadable"
            company.fetch_note = (
                f"Returned no jobs {company.consecutive_empty} times in a row, so it has "
                "been taken out of the workflow."
            )
            company.in_workflow = False
        self.session.add(company)
        return company

    def set_in_workflow(self, company: StarredCompany, enabled: bool) -> bool:
        """True when the change was applied. A company we cannot read refuses to go in."""
        if enabled and company.fetch_method in ("unknown", "unreadable"):
            return False
        company.in_workflow = enabled
        self.session.add(company)
        return True
