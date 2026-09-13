from sqlmodel import Session, select

from ..models.app_setting import AppSetting
from ...shared import now


class AppSettingRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_all(self) -> dict[str, str]:
        return {row.key: row.value for row in self.session.exec(select(AppSetting)).all()}

    def get(self, key: str) -> str | None:
        row = self.session.get(AppSetting, key)
        return row.value if row else None

    def set(self, key: str, value: str) -> AppSetting:
        row = self.session.get(AppSetting, key)
        if row:
            row.value = value
            row.updated_at = now()
        else:
            row = AppSetting(key=key, value=value)
        self.session.add(row)
        return row
