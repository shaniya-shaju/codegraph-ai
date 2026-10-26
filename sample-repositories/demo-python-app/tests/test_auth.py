"""Tests for authentication — calls production code directly (no HTTP
layer), which is also useful for CodeGraph AI's "related tests" signal."""

from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.security.tokens import TokenService
from app.services.auth_service import AuthService


def test_login_returns_token_for_valid_credentials() -> None:
    repo = UserRepository()
    repo.save(
        User(
            user_id="u1",
            email="a@example.com",
            password_hash="hashed:secret123",
            display_name="A",
        )
    )
    service = AuthService(repo, TokenService(signing_key="test-key"))

    token = service.login("a@example.com", "secret123")

    assert token is not None
    assert token.startswith("u1.")


def test_login_returns_none_for_unknown_user() -> None:
    repo = UserRepository()
    service = AuthService(repo, TokenService(signing_key="test-key"))

    token = service.login("missing@example.com", "whatever")

    assert token is None
