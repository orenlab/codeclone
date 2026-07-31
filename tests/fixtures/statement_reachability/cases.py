def after_return(value: int) -> int:
    return value
    value += 1


def after_raise(message: str) -> str:
    raise RuntimeError(message)
    return message


def inside_false_branch() -> str:
    if False:
        return "disabled"
    return "enabled"


def after_break(values: list[int]) -> list[int]:
    for value in values:
        break
        value += 1
    return values


def after_exhaustive_return(flag: bool) -> str:
    if flag:
        return "yes"
    else:
        return "no"
    return "unknown"


def after_partial_return(flag: bool) -> str:
    if flag:
        return "yes"
    return "no"


def after_loop_without_break(values: list[int]) -> int:
    total = 0
    for value in values:
        total += value
    return total


def after_conditional_break(values: list[int]) -> int:
    seen = 0
    for value in values:
        seen += value
        if value > 10:
            break
    return seen


def after_guarded_raise(value: int) -> int:
    if value < 0:
        raise ValueError("negative")
    return value


def constant_binding(value: int) -> int:
    flag = False
    if flag:
        return value + 1
    return value
