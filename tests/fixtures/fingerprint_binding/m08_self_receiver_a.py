# mypy: ignore-errors
# ruff: noqa
# Wire fixture: the shapes below are deliberate. Undefined names, shadowed
# imports and unused bindings are what the rows pin, so they are not linted.


class C:
    def f(self, other):
        return self.helper()
