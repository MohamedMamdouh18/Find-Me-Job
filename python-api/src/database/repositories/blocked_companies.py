from sqlmodel import Session, select

from ..models.blocked_company import BlockedCompany


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
        if not company_name:
            return False
        return self.find_by_name(company_name.lower().strip()) is not None

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
        """Remove if present, add if missing. Returns (is_blocked_after, entry_or_none)."""
        name_lower = company_name.lower().strip()
        existing = self.find_by_name(name_lower)
        if existing:
            self.session.delete(existing)
            return False, None
        entry = BlockedCompany(company_name=name_lower)
        self.session.add(entry)
        return True, entry
