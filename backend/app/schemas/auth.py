"""Auth / OTP API schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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
    """Final registration step — INVITATION-CODE ONLY.

    `invitation_code` is mandatory: without a valid, unused, unexpired,
    non-deleted invitation no account is created and no role is selectable.
    The invitation record is the source of truth for the account's email,
    full name and role; the client can only supply the OTP-verified mobile
    (via `token`) and the password.
    """

    token: str = Field(min_length=20, max_length=2000)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=72)
    # Optional here so the endpoint can answer with the friendly "required"
    # message instead of a field-validation error.
    invitation_code: str | None = Field(default=None, max_length=64)


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


# --- Invitation-code management (the ONLY registration path) ---------------

class InvitationUserCreate(BaseModel):
    """Admin invite form: Full Name, Email, Role — nothing else.

    The admin does NOT set a password and does NOT collect a mobile number:
    the invited person registers with the code + their email, verifies their
    OWN mobile via the existing MSG91 OTP flow (purpose=register), then sets
    their own password. The account always receives the invitation's role.
    """

    role: Literal["admin", "environmental_officer", "mine_manager", "safety_officer"]
    full_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=5, max_length=255)


class InvitationCodeResponse(BaseModel):
    """A created/re-generated invitation. The `code` is the shareable secret:
    it stays visible to the creator (management list) until the invitation is
    used, expired or deleted — it is never hidden after creation.
    """

    id: str
    role: str
    full_name: str
    email: str
    code: str
    expires_at: datetime


class InvitationSummaryResponse(BaseModel):
    """One row of the admin invitation-management list."""

    id: str
    role: str
    full_name: str
    email: str
    # Plaintext code while it exists (legacy rows may have None). Never a hash.
    code: str | None
    status: Literal["Active", "Used", "Expired", "Deleted"]
    created_by: str | None  # email of the inviting admin
    created_at: datetime
    expires_at: datetime


class InvitationValidateRequest(BaseModel):
    """Public pre-flight check: invitation code + the email it is bound to."""

    code: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=5, max_length=255)


class InvitationValidateResponse(BaseModel):
    """What a valid code+email pair may show before the OTP step — the role is
    fixed by the invitation and never chosen by the registering user."""

    role: str
    full_name: str
    expires_at: datetime
