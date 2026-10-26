"""Flask-blueprint-style route decorators."""

from flask import Blueprint

blueprint = Blueprint("health", __name__)


@blueprint.route("/health")
def health():
    return "ok"


@blueprint.route("/login", methods=["POST"])
def login():
    return "ok"
