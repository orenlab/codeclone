# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""One narrowing rule for every closed string vocabulary a reader admits.

A reader that restates a vocabulary by hand -- a ``match`` ladder, a literal
set -- is a second authority over it, and the two drift apart in silence: the
cache's rehydration ladder for runtime-reachability frameworks was one member
short of the model's ``Literal`` for three and a half months, and every warm
run threw the missing member's facts away (measured 2026-10-13). Narrowing
against the members of the declaring alias, taken with ``typing.get_args``,
leaves nothing to keep in step.
"""

from __future__ import annotations

from typing import TypeVar

__all__ = ["narrow_to_vocabulary"]

_MemberT = TypeVar("_MemberT", bound=str)


def narrow_to_vocabulary(
    value: object,
    vocabulary: tuple[_MemberT, ...],
) -> _MemberT | None:
    """The member of ``vocabulary`` that ``value`` spells, or ``None``.

    ``vocabulary`` is always ``get_args`` of the alias that declares it, held
    in a module constant typed by that alias, so the member returned carries
    the alias's type without a cast.
    """

    if not isinstance(value, str):
        return None
    for member in vocabulary:
        if value == member:
            return member
    return None
