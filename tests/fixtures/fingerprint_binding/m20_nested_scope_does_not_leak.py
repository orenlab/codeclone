# mypy: ignore-errors
# ruff: noqa
# Wire fixture: the shapes below are deliberate. Undefined names, shadowed
# imports and unused bindings are what the rows pin, so they are not linted.

import json


def outer(x):
    def inner():
        json = _make()
        return json

    return json.dumps(x)
