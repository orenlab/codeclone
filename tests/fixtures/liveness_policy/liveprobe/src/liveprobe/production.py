def called_from_production(value: int) -> int:
    return value * 2


def test_only_helper(value: int) -> int:
    """Referenced only from tests: dead under production-liveness policy."""
    return value - 1


def unused_private(value: int) -> int:
    """Neither production nor tests reference this symbol."""
    return value + 99
