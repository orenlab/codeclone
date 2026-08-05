from plugkit import HookspecMarker  # type: ignore[import-not-found]

hookspec = HookspecMarker("masquerade")


@hookspec  # type: ignore[untyped-decorator]
def shadow_contract() -> str:
    return "shadow"
