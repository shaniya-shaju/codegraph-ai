"""Email/password authentication for CodeGraph AI."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.config import get_settings
from app.core.database import Base, get_db, init_db

router = APIRouter(prefix="/auth", tags=["authentication"])


class UserRecord(Base):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


init_db()


class RegisterBody(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Please enter your name.")
        return value


class LoginBody(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserView(BaseModel):
    user_id: str
    name: str
    email: str


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserView


# PBKDF2 is in Python's standard library and requires no extra dependency.
def _hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    salt_b64 = base64.urlsafe_b64encode(salt).decode()
    digest_b64 = base64.urlsafe_b64encode(digest).decode()
    return f"pbkdf2_sha256$600000${salt_b64}${digest_b64}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_text, digest_text = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _secret() -> bytes:
    value = get_settings().auth_secret_key
    if len(value) < 32 or value.lower().startswith("replace-") or "changeme" in value.lower():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Authentication is not configured. "
                "Set AUTH_SECRET_KEY to a random value of at least 32 characters."
            ),
        )
    return value.encode()


def issue_token(user_id: str) -> tuple[str, int]:
    ttl = max(1, get_settings().auth_token_expiry_hours) * 3600
    payload = f"{user_id}:{int(time.time()) + ttl}"
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}:{signature}", ttl


def validate_token(token: str) -> str | None:
    try:
        user_id, expiry, signature = token.rsplit(":", 2)
        payload = f"{user_id}:{expiry}"
        expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected) or int(expiry) < int(time.time()):
            return None
        return user_id
    except (ValueError, HTTPException):
        return None


def _response(user: UserRecord) -> AuthResponse:
    token, ttl = issue_token(user.user_id)
    return AuthResponse(
        access_token=token,
        expires_in=ttl,
        user=UserView(user_id=user.user_id, name=user.name, email=user.email),
    )


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(body: RegisterBody, db: Annotated[Session, Depends(get_db)]) -> AuthResponse:
    email = str(body.email).lower().strip()
    if db.scalar(select(UserRecord).where(UserRecord.email == email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    if not re.search(r"[A-Za-z]", body.password) or not re.search(r"\d", body.password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must contain at least one letter and one number.",
        )
    user = UserRecord(
        user_id=secrets.token_hex(16),
        name=body.name,
        email=email,
        password_hash=_hash_password(body.password),
    )
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Could not create account. The email may already be registered.",
        ) from exc
    return _response(user)


@router.post("/login", response_model=AuthResponse)
def login(body: LoginBody, db: Annotated[Session, Depends(get_db)]) -> AuthResponse:
    user = db.scalar(select(UserRecord).where(UserRecord.email == str(body.email).lower().strip()))
    if not user or not _verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
        )
    return _response(user)
