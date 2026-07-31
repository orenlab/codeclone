from .production import used_by_runtime


def execute(quantity: int) -> int:
    return used_by_runtime(quantity)
