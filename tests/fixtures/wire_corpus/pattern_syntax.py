# mypy: ignore-errors
# ruff: noqa


def patterns(subject):
    match subject:
        case 1:
            return "constant"
        case True:
            return "singleton"
        case [head, *tail]:
            return head, tail
        case {"key": value, **rest}:
            return value, rest
        case Point(1, y=captured):
            return captured
        case Color.RED:
            return "value"
        case 2 | 3:
            return "or"
        case captured if captured > 0:
            return captured
        case _:
            return None


def injected_successors(subject):
    match subject:
        case "a|SUCCESSORS:0":
            return True
        case _:
            return False


def injected_block(subject):
    match subject:
        case "BLOCK[0]:":
            return True
        case _:
            return False
