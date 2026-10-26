"""User domain model."""


class User:
    """A registered user account."""

    def __init__(self, user_id: str, email: str, password_hash: str, display_name: str) -> None:
        self.user_id = user_id
        self.email = email
        self.password_hash = password_hash
        self.display_name = display_name


def format_user_display_name(user: User) -> str:
    """An isolated utility function — deliberately never called anywhere
    else in this demo repository (see CodeGraph AI's change-impact
    analysis: this should show zero direct/transitive callers)."""
    return f"{user.display_name} <{user.email}>"
