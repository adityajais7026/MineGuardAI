"""User API schemas."""
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, EmailStr, Field

UserRole = Literal["admin", "mine_manager", "safety_officer", "environmental_officer"]


def _uuid() -> str:
    return str(uuid4())


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = "safety_officer"
    is_active: bool = True
    # E.164-without-'+' verified mobile (MSG91 OTP login). Never accepted from
    # ordinary updates; changes require OTP re-verification (future work).
    mobile: str | None = Field(default=None, max_length=15)


class UserCreate(UserBase):
    """Creating a user sets the initial password (hashed server-side)."""

    password: str = Field(min_length=8, max_length=72, description="Initial password (bcrypt-hashed server-side)")


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)
    mobile: str | None = Field(default=None, max_length=15)


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(default_factory=_uuid)
    created_at: datetime
    updated_at: datetime
    # hashed_password is intentionally never exposed.
