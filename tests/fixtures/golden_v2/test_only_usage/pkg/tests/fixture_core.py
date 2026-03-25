# mypy: ignore-errors

from pkg.core import orphan


def test_orphan() -> None:
    assert orphan(4) == 3
