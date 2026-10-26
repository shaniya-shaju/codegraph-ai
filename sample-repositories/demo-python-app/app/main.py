"""Demo application entry point.

Not executed by CodeGraph AI or any of its scripts — see the repository
README.md ("CodeGraph analyzes source statically; it should not execute
this repository."). This file exists purely so the demo repository's
architecture reads naturally end-to-end.
"""

from fastapi import FastAPI

from app.api.auth import app as auth_router
from app.api.users import app as users_router

app = FastAPI(title="CodeGraph AI Demo App")
app.include_router(auth_router)
app.include_router(users_router)
