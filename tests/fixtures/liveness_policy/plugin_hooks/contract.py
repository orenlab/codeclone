from pluggy import HookspecMarker

hookspec = HookspecMarker("demoapp")


@hookspec
def demo_setting_loaded(name: str) -> None:
    """Extension contract: a setting was loaded."""


@hookspec(firstresult=True)
def demo_resolve_backend(name: str) -> str | None:
    """Extension contract: resolve a backend by name."""
