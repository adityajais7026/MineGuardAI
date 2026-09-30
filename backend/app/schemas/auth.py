"""Auth / OTP API schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.user import UserRole


class OtpRequestBase(BaseModel):
    mobile: str = Field(min_length=8, max_length=20, description="Mobile number (10-15 digits, any common format)")


class OtpSendRequest(OtpRequestBase):
    pass


class OtpVerifyRequest(BaseModel):
    mobile: str = Field(min_length=8, max_length=20, description="Same mobile the OTP was sent to")
    otp: str = Field(min_length=4, max_length=8, pattern=r"^\d{4,8}$")


class RegisterStartRequest(OtpRequestBase):
    pass


class RegisterCompleteRequest(BaseModel):
    token: str = Field(min_length=20, max_length=2000)
    email: str = Field(min_length=5, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=72)
    role: UserRole = "safety_officer"
    invitation_code: str | None = Field(default=None, max_length=200)


class RegisterVerifyResponse(BaseModel):
    token: str
    mobile_masked: str
    expires_in_minutes: int


class RegisterResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class OtpSendResponse(BaseModel):
    mobile_masked: str
    cooldown_seconds: int
    expires_in_minutes: int


class LoginStartRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=72)


class LoginStartResponse(BaseModel):
    otp_required: bool = True
    mobile_masked: str | None = None
    cooldown_seconds: int | None = None
    expires_in_minutes: int | None = None


class LoginVerifyRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    otp: str = Field(min_length=4, max_length=8, pattern=r"^\d{4,8}$")


class InvitationCreateRequest(BaseModel):
    role: Literal["admin", "environmental_officer"]
    note: str | None = Field(default=None, max_length=255)
    bound_email: str | None = Field(default=None, max_length=255)
    bound_mobile: str | None = Field(default=None, max_length=20)
    expires_in_minutes: int = Field(default=2880, ge=1, le=10080)  # 2 days default, max 7 days


class InvitationResponse(BaseModel):
    id: str
    role: str
    code: str  # shown ONCE, to the inviting admin
    note: str | None = None
    expires_at: datetime


# --- "Invite User" link invitations (no mobile, admin sets no password) ---

class InvitationUserCreate(BaseModel):
    """Admin invite form: Full Name, Email, Role — nothing else.

    The admin does NOT set a password and does NOT collect a mobile number:
    the invited person sets their own password on the accept page, and the
    account is created without a mobile (no MSG91 involvement).
    """

    role: Literal["admin", "environmental_officer", "mine_manager", "safety_officer"]
    full_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=5, max_length=255)


class InvitationLinkResponse(BaseModel):
    id: str
    role: str
    invited_name: str
    invited_email: str
    invitation_url: str  # shown ONCE, to the inviting admin
    token: str  # the raw link token (same ONCE constraint as `code` above)
    expires_at: datetime


class InvitationPublicResponse(BaseModel):
    """What an accept page may show for a valid token — no IDs, no secrets."""

    full_name: str
    email: str
    role: str
    expires_at: datetime


class InvitationAcceptRequest(BaseModel):
    password: str = Field(min_length=8, max_length=72)
    # Confirmed client-side; server enforces correctness via the two fields.
    confirm_password: str = Field(min_length=8, max_length=72)
