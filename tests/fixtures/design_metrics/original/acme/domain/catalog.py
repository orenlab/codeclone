"""Call targets of three different kinds, so a call position can be judged.

``Invoice`` and ``Receipt`` are classes; ``build_reference`` is a plain
function; ``audit`` is a decorator factory. All four are imported the same way
and are indistinguishable at the call site without resolving the binding.
"""

from collections.abc import Callable

_Method = Callable[..., None]


def build_reference(value: str) -> str:
    return value


def audit(*, level: int = 0) -> Callable[[_Method], _Method]:
    def decorate(method: _Method) -> _Method:
        return method

    return decorate


class Invoice:
    def __init__(self, number: int = 0) -> None:
        self.number = number


class Receipt:
    def __init__(self, number: int = 0) -> None:
        self.number = number
