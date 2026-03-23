from typing import Optional

from sqlmodel import Session, select

from ..models import CVKeywords


class CVKeywordsRepository:
    def __init__(self, session: Session):
        self.session = session

    def hash_exists(self, cv_hash: str) -> bool:
        statement = select(CVKeywords).where(CVKeywords.cv_hash == cv_hash)
        return self.session.exec(statement).first() is not None

    def get_latest(self) -> Optional[CVKeywords]:
        statement = select(CVKeywords).order_by(CVKeywords.updated_at.desc()).limit(1)  # type: ignore
        return self.session.exec(statement).first()

    def save(self, cv_hash: str, keywords: str):
        existing = self.session.get(CVKeywords, 1)
        if existing:
            existing.cv_hash = cv_hash
            existing.keywords = keywords
            self.session.add(existing)
        else:
            self.session.add(CVKeywords(id=1, cv_hash=cv_hash, keywords=keywords))
