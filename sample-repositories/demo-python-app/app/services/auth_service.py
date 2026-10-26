"""Authentication business logic."""

from app.repositories.user_repository import UserRepository
from app.security.tokens import TokenService


class AuthService:
    """Authenticates users and issues access tokens."""

    def __init__(self, user_repository: UserRepository, token_service: TokenService) -> None:
        self._user_repository = user_repository
        self._token_service = token_service

    def login(self, email: str, password: str) -> str | None:
        """Authenticate a user by email/password and return an access
        token, or None if the credentials don't match a known user."""
        user = self._user_repository.find_by_email(email)
        if user is None:
            return None
        if not self._check_password(user.password_hash, password):
            return None
        return self._token_service.create_access_token(user.user_id)

    def _check_password(self, password_hash: str, password: str) -> bool:
        """Very small placeholder check — not real password hashing (this
        is a demo repository; see its README)."""
        return password_hash == f"hashed:{password}"
