def past_result(item: int) -> int:
    return item
    item += 1


def past_error(detail: str) -> str:
    raise RuntimeError(detail)
    return detail


def inside_disabled_branch() -> str:
    if False:
        return "closed"
    return "open"


def past_stop(entries: list[int]) -> list[int]:
    for entry in entries:
        break
        entry += 1
    return entries


def past_complete_choice(enabled: bool) -> str:
    if enabled:
        return "active"
    else:
        return "inactive"
    return "pending"


def past_partial_result(enabled: bool) -> str:
    if enabled:
        return "active"
    return "inactive"


def past_loop_without_stop(entries: list[int]) -> int:
    amount = 0
    for entry in entries:
        amount += entry
    return amount


def past_conditional_stop(entries: list[int]) -> int:
    counted = 0
    for entry in entries:
        counted += entry
        if entry > 10:
            break
    return counted


def past_guarded_error(number: int) -> int:
    if number < 0:
        raise ValueError("negative")
    return number


def steady_binding(number: int) -> int:
    enabled = False
    if enabled:
        return number + 1
    return number
