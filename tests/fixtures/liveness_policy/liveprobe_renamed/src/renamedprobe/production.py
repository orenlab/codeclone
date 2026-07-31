def used_by_runtime(quantity: int) -> int:
    return quantity * 11


def held_by_checks(quantity: int) -> int:
    """Only verification code retains this production symbol."""
    return quantity - 13


def forgotten_worker(quantity: int) -> int:
    """No runtime or verification path retains this symbol."""
    return quantity + 101
