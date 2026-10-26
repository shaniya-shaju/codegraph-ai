"""Keyword-only parameters, with and without a *args before the marker."""


def configure(*, debug=False, level="info"):
    return debug, level


def send(message, *args, retries=1, timeout=5):
    return message, args, retries, timeout
