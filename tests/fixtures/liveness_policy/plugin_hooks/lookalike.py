from collections.abc import Callable


def hookspec(function: Callable[[], str]) -> Callable[[], str]:
    return function


@hookspec
def tracked_report() -> str:
    return "tracked"
