from collections.abc import Callable

from opaque_contract import Adapter  # type: ignore[import-not-found]
from opaque_runtime import subscribe  # type: ignore[import-not-found]

HOOKS: list[Callable[[], str]] = []


@subscribe("readiness")  # type: ignore[untyped-decorator]
def opaque_listener() -> str:
    return "prepared"


def nearby_wrapper(callback: Callable[[], str]) -> Callable[[], str]:
    return callback


@nearby_wrapper
def nearby_listener() -> str:
    return "nearby"


class ForeignAdapter(Adapter):  # type: ignore[misc]
    def process(self, message: str) -> str:
        return message


class NearbyBase:
    def process(self, message: str) -> str:
        return message


class NearbyAdapter(NearbyBase):
    def process(self, message: str) -> str:
        return message.swapcase()


class ProvenAdapter(Adapter):  # type: ignore[misc]
    def transform(self, message: str) -> str:
        return message


class CollidingAdapter(Adapter):  # type: ignore[misc]
    def fetch(self, token: str) -> str:
        return token


class NearbyCache:
    def fetch(self, token: str) -> str:
        return token


class MaskedAdapter(Adapter):  # type: ignore[misc]
    def __hidden(self, message: str) -> str:
        return message


class SelfRoutingAdapter(Adapter):  # type: ignore[misc]
    # `self` inside the declaring class IS a proven receiver type, so the
    # self-call below is decision-table row 1 for `_prepare` and roots it even
    # though the class hangs off an opaque base. `gather` itself carries no
    # evidence and still abstains.
    def gather(self, message: str) -> str:
        return self._prepare(message)

    def _prepare(self, message: str) -> str:
        return message.strip()


class SharedNameAdapter(Adapter):  # type: ignore[misc]
    # Negative twin for self-dispatch: `_prepare` is self-called in the
    # unrelated class below, never here. A self-call proves only its own
    # class's receiver, so this method must keep abstaining.
    def _prepare(self, message: str) -> str:
        return message


class DetachedDispatcher:
    def steer(self, message: str) -> str:
        return self._prepare(message)

    def _prepare(self, message: str) -> str:
        return message.lower()


def exercise_typed_receivers(adapter: ProvenAdapter, cache: NearbyCache) -> str:
    # Both call sites name the declaring class, so the receiver type is proven.
    # NearbyCache.fetch proves NearbyCache.fetch only: it must never revive the
    # identically named CollidingAdapter.fetch on the opaque external base.
    return ProvenAdapter.transform(adapter, "message") + NearbyCache.fetch(cache, "tok")


def attached_hook() -> str:
    return "attached"


HOOKS.append(attached_hook)


def detached_hook() -> str:
    return "detached"
