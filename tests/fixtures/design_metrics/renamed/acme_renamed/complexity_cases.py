"""Renamed functions with manually countable cyclomatic complexity."""


def direct_scale(number: int) -> int:
    return number * 2


def decision_scale(number: int, active: bool, entries: list[int]) -> int:
    result = 0
    if active:
        result += 1
    if number > 10:
        result += 2
    elif number < 0:
        result -= 2
    for entry in entries:
        if entry:
            result += 1
    try:
        result += 10 // number
    except ZeroDivisionError:
        result = 0
    return result
