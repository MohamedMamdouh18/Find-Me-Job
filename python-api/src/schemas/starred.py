from typing import Optional

from pydantic import BaseModel

from .companies import CareersUrl, CompanyName


class StarredCompanyCreate(BaseModel):
    company_name: CompanyName
    careers_url: CareersUrl = None
    notes: Optional[str] = None


class StarredCompanyUpdate(BaseModel):
    careers_url: CareersUrl = None
    notes: Optional[str] = None


class StarredCompanyToggle(BaseModel):
    company_name: CompanyName
