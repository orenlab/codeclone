from collections.abc import Callable

Endpoint = Callable[[], dict[str, str]]

ROUTES: dict[str, Endpoint] = {}
STARTUP_CALLBACKS: list[Callable[[], None]] = []


def route(path: str) -> Callable[[Endpoint], Endpoint]:
    def register(function: Endpoint) -> Endpoint:
        ROUTES[path] = function
        return function

    return register


@route("/health")
def health_endpoint() -> dict[str, str]:
    return {"status": "ok"}


def startup_callback() -> None:
    ROUTES.setdefault("/startup", health_endpoint)


STARTUP_CALLBACKS.append(startup_callback)
