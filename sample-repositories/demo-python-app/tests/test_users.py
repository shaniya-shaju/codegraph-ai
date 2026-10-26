"""Tests for user registration."""

from app.repositories.user_repository import UserRepository
from app.services.user_service import UserService


def test_create_user_persists_a_new_user() -> None:
    repo = UserRepository()
    service = UserService(repo)

    user = service.create_user("new@example.com", "longpassword", "New User")

    assert repo.find_by_email("new@example.com") is user


def test_create_user_rejects_short_password() -> None:
    repo = UserRepository()
    service = UserService(repo)

    try:
        service.create_user("new@example.com", "short", "New User")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
