# mypy: ignore-errors
# ruff: noqa
# Wire fixture: the shapes below are deliberate. Undefined names, shadowed
# imports and unused bindings are what the rows pin, so they are not linted.


class C:
    def method(self, values):
        def inner(value):
            return self.handle(value)

        return inner
