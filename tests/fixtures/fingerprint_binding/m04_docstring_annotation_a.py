# mypy: ignore-errors
# ruff: noqa
# Wire fixture: the shapes below are deliberate. Undefined names, shadowed
# imports and unused bindings are what the rows pin, so they are not linted.


def f(x: int) -> int:
    """First wording."""
    total = x + 1
    return total
