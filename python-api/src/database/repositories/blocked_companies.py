from sqlmodel import Session, select

from ..models.blocked_company import BlockedCompany
from ...services.identity import normalise_company


class BlockedCompanyRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_all(self, search: str | None = None) -> list[BlockedCompany]:
        statement = select(BlockedCompany).order_by(BlockedCompany.company_name.asc())  # type: ignore[arg-type]
        if search:
            statement = statement.where(
                BlockedCompany.company_name.contains(search.lower().strip())  # type: ignore[union-attr]
            )
        return list(self.session.exec(statement).all())

    def get_names(self) -> list[str]:
        return list(self.session.exec(select(BlockedCompany.company_name)).all())

    def find_by_name(self, company_name_lower: str) -> BlockedCompany | None:
        return self.session.exec(
            select(BlockedCompany).where(BlockedCompany.company_name == company_name_lower)
        ).first()

    def is_blocked(self, company_name: str) -> bool:
        """Matched on the normalised name, so blocking "Acme" also blocks "Acme, Inc.".

        Exact matching let the same employer keep arriving nightly under a slightly
        different spelling, which made the one loop the user relies on look broken.
        """
        if not company_name:
            return False
        if self.find_by_name(company_name.lower().strip()) is not None:
            return True
        wanted = normalise_company(company_name)
        if not wanted:
            return False
        return any(normalise_company(row.company_name) == wanted for row in self.get_all())

    def add(self, company_name: str, reason: str | None = None) -> BlockedCompany:
        entry = BlockedCompany(company_name=company_name.lower().strip(), reason=reason or None)
        self.session.add(entry)
        return entry

    def delete(self, id: int) -> bool:
        entry = self.session.get(BlockedCompany, id)
        if not entry:
            return False
        self.session.delete(entry)
        return True

    def update(self, id: int, reason: str | None) -> bool:
        entry = self.session.get(BlockedCompany, id)
        if not entry:
            return False
        entry.reason = reason or None
        self.session.add(entry)
        return True

    def toggle(self, company_name: str) -> tuple[bool, BlockedCompany | None]:
        """Remove if present, add if missing. Returns (is_blocked_after, entry_or_none).

        Presence is judged the way is_blocked judges it, and unblocking removes every
        spelling that matches: otherwise "Acme, Inc." reports unblocked while "acme" keeps
        dropping its postings.
        """
        name_lower = company_name.lower().strip()
        wanted = normalise_company(company_name)
        matches = [
            row for row in self.get_all()
            if row.company_name == name_lower
            or (wanted and normalise_company(row.company_name) == wanted)
        ]
        if matches:
            for row in matches:
                self.session.delete(row)
            return False, None
        entry = BlockedCompany(company_name=name_lower)
        self.session.add(entry)
        return True, entry
