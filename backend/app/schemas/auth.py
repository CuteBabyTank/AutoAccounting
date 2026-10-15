"""Auth, team and platform-admin request/response schemas."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


class GoogleAuthRequest(BaseModel):
    credential: str  # The ID token from Google


class UserResponse(BaseModel):
    id: str
    email: str
    nickname: Optional[str] = None
    role: str = "unverified"
    organization_name: Optional[str] = None
    is_active: bool = True
    enterprise_id: Optional[str] = None
    pages_used: Optional[int] = None
    budget: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    token: str
    user: UserResponse


class UpdateMeRequest(BaseModel):
    nickname: Optional[str] = Field(default=None, max_length=100)


# --- Team (firm staff) ---
class AddMemberRequest(BaseModel):
    """Attach an existing UNVERIFIED signup to the calling firm as an employee."""
    email: EmailStr


class UpdateMemberRequest(BaseModel):
    is_active: Optional[bool] = None


class MemberResponse(BaseModel):
    id: str
    email: str
    nickname: Optional[str] = None
    role: str
    is_active: bool
    created_at: datetime


class FirmUsageResponse(BaseModel):
    organization_name: Optional[str] = None
    pages_used: int
    year: int
    month: int
    budget: float
    billing_enabled: bool


# --- Platform admin ---
class AccountOverview(BaseModel):
    id: str
    email: str
    nickname: Optional[str] = None
    role: str
    is_active: bool
    organization_name: Optional[str] = None
    enterprise_id: Optional[str] = None
    enterprise_email: Optional[str] = None
    pages_used: int = 0
    budget: float = 0.0
    created_at: datetime


class PromoteFirmRequest(BaseModel):
    organization_name: Optional[str] = Field(default=None, max_length=255)


class SetUserRoleRequest(BaseModel):
    role: str = Field(..., pattern="^(enterprise|manager|employee|unverified)$")
    enterprise_id: Optional[str] = None


class SetPageRateRequest(BaseModel):
    """Platform-wide flat rate per extracted page; null turns billing off."""
    page_rate: Optional[float] = Field(default=None, gt=0, le=10_000)


class PageRateResponse(BaseModel):
    page_rate: Optional[float] = None


class AdjustBudgetRequest(BaseModel):
    operation: str = Field(..., pattern="^(add|subtract|set)$")
    amount: float = Field(default=0.0, ge=0, le=1_000_000_000)


class BudgetResponse(BaseModel):
    budget: float = 0.0
