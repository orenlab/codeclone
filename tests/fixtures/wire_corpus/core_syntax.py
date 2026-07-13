# mypy: ignore-errors
# ruff: noqa

import contextlib as contexts
from collections.abc import Iterable
from package import symbol as imported_symbol


STATE = 0


@decorate(mode="fast")
def core(
    positional: int,
    /,
    value: int = 1,
    *items: int,
    named: str = "value",
    **options: object,
) -> str:
    """This docstring is removed by the default normalization policy."""
    global STATE
    total: int = 1 + 2
    total += 3
    values = [item * 2 for item in items if item]
    mapping = {str(item): item for item in values}
    unique = {item for item in values}
    stream = (item for item in values)
    selected = values[1:-1:2]
    pair = (named, *selected)
    decision = named if value else "fallback"
    predicate = lambda candidate: candidate is not None
    if value and predicate(decision):
        STATE = imported_symbol(value, option=options.get("key"))
    elif not (value in unique):
        STATE = 0
    else:
        STATE = -value
    for item in stream:
        if item < 0:
            continue
        if item > 100:
            break
    while value:
        value -= 1
    with contexts.nullcontext(pair) as entered:
        assert entered, "entered"
    try:
        result = mapping[named]
    except errors.CustomError as error:
        raise RuntimeError("failed") from error
    else:
        del mapping[named]
    finally:
        pass
    if captured := result:
        return f"{captured!r:>10}"
    return named


def generator(values: Iterable[int]):
    yield from values
    yield None


async def async_core(source, manager):
    await source.ready()
    async with manager as resource:
        async for item in source:
            resource.send(item)
    return resource
