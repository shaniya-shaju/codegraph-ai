"""User registration business logic."""

import uuid

from app.models.user import User
from app.repositories.user_repository import UserRepository


def validate_credentials(email: str, password: str) -> bool:
    """A different ``validate_credentials`` than
    app.security.tokens.validate_credentials — same short name,
    different module, on purpose (see the demo repository's README:
    "multiple functions named similarly enough to test symbol
    ambiguity")."""
    return "@" in email and len(password) >= 8


class UserService:
    """Registers new users."""

    def __init__(self, user_repository: UserRepository) -> None:
        self._user_repository = user_repository

    def create_user(self, email: str, password: str, display_name: str) -> User:
        """Validate and persist a new user account."""
        if not validate_credentials(email, password):
            raise ValueError("Invalid email or password.")
        user = User(
            user_id=str(uuid.uuid4()),
            email=email,
            password_hash=f"hashed:{password}",
            display_name=display_name,
        )
        return self._user_repository.save(user)
