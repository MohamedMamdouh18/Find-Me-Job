from typing import Optional

from pydantic import BaseModel


class BlockedCompanyCreate(BaseModel):
    company_name: str
    reason: Optional[str] = None


class BlockedCompanyUpdate(BaseModel):
    reason: Optional[str] = None


class BlockedCompanyToggle(BaseModel):
    company_name: str
