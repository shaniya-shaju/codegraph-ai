"""FastAPI-style route decorators."""

from fastapi import APIRouter

app = APIRouter()


@app.get("/users")
def list_users():
    return []


@app.post("/users")
def create_user():
    return {}


@app.delete("/users/{user_id}")
def delete_user(user_id):
    return None
