"""Authentication endpoints (JWT-based; Supabase Auth adapter arrives Phase 11+).

Password hashes live only in the users table (bcrypt). Tokens carry sub/role
and are verified by app.core.security.get_current_user.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    get_current_user,
    get_db,
    verify_password,
)
from app.database.models import User
from app.schemas.user import UserResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("/login")
def login(db: DbSession, form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    """OAuth2 password flow; returns a bearer token usable in Swagger too."""
    user = db.scalar(select(User).where(User.email == form.username))
    if user is None or user.hashed_password is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    token = create_access_token(subject=user.id, role=user.role)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": UserResponse.model_validate(user),
    }


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(get_current_user)]):
    """Current authenticated user profile."""
    return user
