# mypy: ignore-errors


def helper(value: int) -> int:
    return value + 1


def live(value: int) -> int:
    result = helper(value)
    return result


def orphan(value: int) -> int:
    return value - 1
