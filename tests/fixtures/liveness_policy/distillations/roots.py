from collections.abc import Callable

from external_framework import register  # type: ignore[import-not-found]
from external_protocol import Handler  # type: ignore[import-not-found]

CALLBACKS: list[Callable[[], str]] = []


@register("health")  # type: ignore[untyped-decorator]
def framework_handler() -> str:
    return "healthy"


def local_decorator(function: Callable[[], str]) -> Callable[[], str]:
    return function


@local_decorator
def locally_decorated() -> str:
    return "local"


class ProtocolHandler(Handler):  # type: ignore[misc]
    def handle(self, payload: str) -> str:
        return payload


class LocalBase:
    def handle(self, payload: str) -> str:
        return payload


class LocalHandler(LocalBase):
    def handle(self, payload: str) -> str:
        return payload.upper()


class EvidencedHandler(Handler):  # type: ignore[misc]
    def process(self, payload: str) -> str:
        return payload


class NameCollisionHandler(Handler):  # type: ignore[misc]
    def get(self, key: str) -> str:
        return key


class LocalStore:
    def get(self, key: str) -> str:
        return key


class MangledHandler(Handler):  # type: ignore[misc]
    def __secret(self, payload: str) -> str:
        return payload


class SelfDispatchHandler(Handler):  # type: ignore[misc]
    # `self` inside the declaring class IS a proven receiver type, so the
    # self-call below is decision-table row 1 for `_gather` and roots it even
    # though the class hangs off an opaque base. `collect` itself carries no
    # evidence and still abstains.
    def collect(self, payload: str) -> str:
        return self._gather(payload)

    def _gather(self, payload: str) -> str:
        return payload.strip()


class SharedNameHandler(Handler):  # type: ignore[misc]
    # Negative twin for self-dispatch: `_gather` is self-called in the
    # unrelated class below, never here. A self-call proves only its own
    # class's receiver, so this method must keep abstaining.
    def _gather(self, payload: str) -> str:
        return payload


class UnrelatedDispatcher:
    def drive(self, payload: str) -> str:
        return self._gather(payload)

    def _gather(self, payload: str) -> str:
        return payload.lower()


def drive_proven_receivers(handler: EvidencedHandler, store: LocalStore) -> str:
    # Both call sites name the declaring class, so the receiver type is proven.
    # LocalStore.get proves LocalStore.get only: it must never revive the
    # identically named NameCollisionHandler.get on the opaque external base.
    return EvidencedHandler.process(handler, "payload") + LocalStore.get(store, "key")


def registered_callback() -> str:
    return "registered"


CALLBACKS.append(registered_callback)


def unregistered_callback() -> str:
    return "unregistered"
