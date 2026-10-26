"""Authentication API routes."""

from fastapi import APIRouter

from app.repositories.user_repository import UserRepository
from app.security.tokens import TokenService
from app.services.auth_service import AuthService

app = APIRouter()

_user_repository = UserRepository()
_token_service = TokenService(signing_key="demo-signing-key")
_auth_service = AuthService(_user_repository, _token_service)


@app.post("/login")
def login_endpoint(email: str, password: str) -> dict:
    """POST /login — authenticate a user and return an access token."""
    token = _auth_service.login(email, password)
    if token is None:
        return {"error": "invalid credentials"}
    return {"access_token": token}
