# mypy: ignore-errors
# ruff: noqa
# Wire fixture: the shapes below are deliberate. Undefined names, shadowed
# imports and unused bindings are what the rows pin, so they are not linted.


def outer():
    import json as codec

    def inner(value):
        nonlocal codec
        return codec.dumps(value)

    return inner
