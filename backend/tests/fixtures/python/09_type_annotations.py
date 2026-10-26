"""Parameter and return type annotations."""


def compute(a: int, b: float, label: str = "x") -> bool:
    return bool(a) and bool(b) and bool(label)


def maybe_find(key: str) -> str | None:
    return None
