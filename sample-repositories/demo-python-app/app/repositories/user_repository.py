"""Persistence layer for User records."""

from app.models.user import User


class BaseRepository:
    """Shared repository behavior — every concrete repository extends
    this (see CodeGraph AI's inheritance-impact analysis: changing this
    class potentially affects every subclass)."""

    def __init__(self) -> None:
        self._connected = True

    def is_connected(self) -> bool:
        """Whether the underlying storage connection is currently open."""
        return self._connected


class UserRepository(BaseRepository):
    """Persists and retrieves User records."""

    def __init__(self) -> None:
        super().__init__()
        self._users_by_email: dict[str, User] = {}

    def find_by_email(self, email: str) -> User | None:
        """Look up a user by email address."""
        return self._users_by_email.get(email)

    def save(self, user: User) -> User:
        """Persist a new or updated user record."""
        self._users_by_email[user.email] = user
        return user
