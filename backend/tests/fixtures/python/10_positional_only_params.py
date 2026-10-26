"""PEP 570 positional-only parameters."""


def divide(numerator, denominator, /, precision=2):
    return round(numerator / denominator, precision)
