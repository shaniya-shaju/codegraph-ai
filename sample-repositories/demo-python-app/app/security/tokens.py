"""Access-token issuance."""

import hashlib
import hmac


class TokenService:
    """Issues and (in a real service) would verify access tokens."""

    def __init__(self, signing_key: str) -> None:
        self._signing_key = signing_key

    def create_access_token(self, user_id: str) -> str:
        """Create a signed access token for the given user_id."""
        signature = hmac.new(
            self._signing_key.encode(), user_id.encode(), hashlib.sha256
        ).hexdigest()
        return f"{user_id}.{signature}"


def validate_credentials(email: str, password: str) -> bool:
    """A different ``validate_credentials`` than
    app.services.user_service.validate_credentials — see the demo
    repository's README for why this name is intentionally reused, to
    exercise symbol-ambiguity handling."""
    return bool(email) and len(password) >= 8
