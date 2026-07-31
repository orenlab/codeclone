"""Rename twin of ``acme.domain.catalog``: identifiers renamed, shapes kept."""

from collections.abc import Callable

_Handler = Callable[..., None]


def derive_token(payload: str) -> str:
    return payload


def supervise(*, rank: int = 0) -> Callable[[_Handler], _Handler]:
    def wrap(handler: _Handler) -> _Handler:
        return handler

    return wrap


class Statement:
    def __init__(self, index: int = 0) -> None:
        self.index = index


class Voucher:
    def __init__(self, index: int = 0) -> None:
        self.index = index
