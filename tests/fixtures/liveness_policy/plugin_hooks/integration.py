import pluggy

hookimpl = pluggy.HookimplMarker("hostapp")
impl_marker = hookimpl


@hookimpl(tryfirst=True)
def demo_render_panel(payload: dict[str, str]) -> str:
    return payload["panel"]


@impl_marker
def demo_flush_cache() -> None:
    return None


@pluggy.hookimpl(trylast=True)  # type: ignore[attr-defined, untyped-decorator]
def demo_publish_summary() -> str:
    return "summary"
