from typing import Optional

from pydantic import BaseModel


class StarredCompanyCreate(BaseModel):
    company_name: str
    careers_url: Optional[str] = None
    notes: Optional[str] = None


class StarredCompanyUpdate(BaseModel):
    careers_url: Optional[str] = None
    notes: Optional[str] = None


class StarredCompanyToggle(BaseModel):
    company_name: str
