"""Functions with manually countable cyclomatic complexity."""


def simple(value: int) -> int:
    return value * 2


def branchy(value: int, enabled: bool, items: list[int]) -> int:
    result = 0
    if enabled:
        result += 1
    if value > 10:
        result += 2
    elif value < 0:
        result -= 2
    for item in items:
        if item:
            result += 1
    try:
        result += 10 // value
    except ZeroDivisionError:
        result = 0
    return result
