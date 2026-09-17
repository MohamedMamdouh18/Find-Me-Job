from typing import Optional

from pydantic import BaseModel

from .companies import CompanyName


class BlockedCompanyCreate(BaseModel):
    company_name: CompanyName
    reason: Optional[str] = None


class BlockedCompanyUpdate(BaseModel):
    reason: Optional[str] = None


class BlockedCompanyToggle(BaseModel):
    company_name: CompanyName
