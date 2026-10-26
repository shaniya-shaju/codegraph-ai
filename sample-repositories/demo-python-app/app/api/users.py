"""User management API routes."""

from fastapi import APIRouter

from app.repositories.user_repository import UserRepository
from app.services.user_service import UserService

app = APIRouter()

_user_repository = UserRepository()
_user_service = UserService(_user_repository)


@app.post("/users")
async def create_user_endpoint(email: str, password: str, display_name: str) -> dict:
    """POST /users — register a new user account (async route handler)."""
    user = _user_service.create_user(email, password, display_name)
    return {"user_id": user.user_id, "email": user.email}
