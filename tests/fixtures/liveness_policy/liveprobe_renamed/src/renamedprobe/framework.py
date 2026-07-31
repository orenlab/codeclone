from collections.abc import Callable

View = Callable[[], dict[str, str]]

ENDPOINTS: dict[str, View] = {}
BOOT_HOOKS: list[Callable[[], None]] = []


def endpoint(label: str) -> Callable[[View], View]:
    def attach(callback: View) -> View:
        ENDPOINTS[label] = callback
        return callback

    return attach


@endpoint("/ready")
def readiness_view() -> dict[str, str]:
    return {"condition": "prepared"}


def boot_hook() -> None:
    ENDPOINTS.setdefault("/boot", readiness_view)


BOOT_HOOKS.append(boot_hook)
