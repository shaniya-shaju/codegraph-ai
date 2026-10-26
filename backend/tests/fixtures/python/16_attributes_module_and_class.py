"""Simple module-level and class-level assignment targets."""

DEFAULT_TIMEOUT = 30
API_VERSION: str = "v1"


class Config:
    debug = False
    max_connections: int = 10
