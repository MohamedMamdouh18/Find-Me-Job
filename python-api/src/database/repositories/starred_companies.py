from sqlmodel import Session, select

from ..models.starred_company import StarredCompany


class StarredCompanyRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_all(self, search: str | None = None) -> list[StarredCompany]:
        statement = select(StarredCompany).order_by(StarredCompany.company_name.asc())  # type: ignore[arg-type]
        if search:
            statement = statement.where(
                StarredCompany.company_name.contains(search.lower().strip())  # type: ignore[union-attr]
            )
        return list(self.session.exec(statement).all())

    def get_names(self) -> list[str]:
        """Return all starred company names (lowercase) for bulk client-side checks."""
        return list(self.session.exec(select(StarredCompany.company_name)).all())

    def find_by_name(self, company_name_lower: str) -> StarredCompany | None:
        return self.session.exec(
            select(StarredCompany).where(StarredCompany.company_name == company_name_lower)
        ).first()

    def is_starred(self, company_name: str) -> bool:
        return self.find_by_name(company_name.lower().strip()) is not None

    def add(
        self,
        company_name: str,
        careers_url: str | None = None,
        notes: str | None = None,
    ) -> StarredCompany:
        entry = StarredCompany(
            company_name=company_name.lower().strip(),
            careers_url=careers_url or None,
            notes=notes or None,
        )
        self.session.add(entry)
        return entry

    def delete(self, id: int) -> bool:
        entry = self.session.get(StarredCompany, id)
        if not entry:
            return False
        self.session.delete(entry)
        return True

    def update(self, id: int, careers_url: str | None, notes: str | None) -> bool:
        entry = self.session.get(StarredCompany, id)
        if not entry:
            return False
        if careers_url is not None:
            entry.careers_url = careers_url or None
        if notes is not None:
            entry.notes = notes or None
        self.session.add(entry)
        return True

    def toggle(self, company_name: str) -> tuple[bool, StarredCompany | None]:
        """Remove if exists, add if missing. Returns (is_starred_after, entry_or_none)."""
        name_lower = company_name.lower().strip()
        existing = self.find_by_name(name_lower)
        if existing:
            self.session.delete(existing)
            return False, None
        entry = StarredCompany(company_name=name_lower)
        self.session.add(entry)
        return True, entry
