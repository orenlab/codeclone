# mypy: ignore-errors

from pkg.core import live


def run(value: int) -> int:
    return live(value)
