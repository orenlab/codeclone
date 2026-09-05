# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""What actually makes the open world differ from the closed one.

``tests/test_dead_code_world_matrix.py`` pins WHAT each world concludes from
each kind of support, and it proves each row is caused by its own support by
removing that support and watching the row move. This module asks the other
question: which MECHANISM inside the analyzer produces the difference between
the two worlds at all.

The answer is meant to be exactly one thing - the external-reachability
abstention. Under the open world a symbol with no internal evidence that
external reachability calls reachable is ``unresolved``, never ``dead``; the
closed world removes the unknown external consumer and the same symbol becomes
a finding. If some other mechanism had crept in and were doing part of that
work, both worlds would still answer correctly and every existing pin would
stay green.

So the difference is measured, and then the abstention itself is withdrawn in
a spawned run:

* the open world must then answer EXACTLY what the closed world answered -
  naming the mechanism, not merely moving a count;
* the closed world must be UNCHANGED by the same mutation - the control that
  proves the mutation is specific to the abstention rather than to the lane.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from tests._liveness_report_helpers import (
    analysis_report,
    dead_code_family_of,
    dead_qualnames,
    unresolved_by_qualname,
)

_SCOPE_ID: Final = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f4d"

#: One symbol that MOVES between worlds and one that does not, so a mutation
#: that simply emptied the abstention lane could not pass as a mutation that
#: moved the right symbol.
#:
#: * ``pkg.api`` is public, so its uncalled function is externally reachable
#:   and the open world must abstain on it;
#: * ``pkg._support`` is private, so nothing external can reach it and its
#:   uncalled function is dead in both worlds.
_TREE: Final[dict[str, str]] = {
    "pkg/__init__.py": "\n",
    "pkg/api.py": """
def public_and_uncalled(value: int) -> int:
    return value
""",
    "pkg/_support.py": """
def never_referenced_at_all(value: int) -> int:
    return value - 1
""",
}

_MOVES: Final = "pkg.api:public_and_uncalled"
_STAYS: Final = "pkg._support:never_referenced_at_all"

#: The mutation: ``classify_liveness`` is called with no external reachability
#: at all, which is the abstention withdrawn at its source. Every module that
#: bound the function by name is repointed, because a rebinding importer would
#: keep calling the original and the mutation would silently not apply.
_WITHDRAW_THE_ABSTENTION: Final = (
    "import codeclone.metrics.dead_code as _dead_code\n"
    "_original = _dead_code.classify_liveness\n"
    "def _without_abstention(*args, **kwargs):\n"
    "    kwargs['external_reachability'] = ()\n"
    "    return _original(*args, **kwargs)\n"
    "_dead_code.classify_liveness = _without_abstention\n"
    "import codeclone.core.pipeline as _pipeline\n"
    "import codeclone.metrics.registry as _registry\n"
    "for _module in (_pipeline, _registry):\n"
    "    if getattr(_module, 'classify_liveness', None) is _original:\n"
    "        _module.classify_liveness = _without_abstention\n"
)


def _lanes(payload: dict[str, object]) -> tuple[frozenset[str], frozenset[str]]:
    """What this run called dead, and what it abstained on."""

    family = dead_code_family_of(payload)
    return dead_qualnames(family), frozenset(unresolved_by_qualname(family))


def _world(
    tmp_path: Path, name: str, world: str, *, preamble: str = ""
) -> tuple[frozenset[str], frozenset[str]]:
    return _lanes(
        analysis_report(
            tmp_path,
            _TREE,
            name,
            scope_id=_SCOPE_ID,
            cli_args=() if world == "open" else ("--dead-code-world", world),
            preamble=preamble,
        )
    )


def test_the_two_worlds_differ_on_exactly_the_externally_reachable_symbol(
    tmp_path: Path,
) -> None:
    """The population, before anything is concluded from a difference.

    A pin that only asserted "the worlds differ" would be satisfied by any
    difference anywhere. This names the symbol that moves and the symbol that
    does not, and asserts the moving set is non-empty - an empty one would
    make every assertion below vacuously true.
    """

    open_dead, open_unresolved = _world(tmp_path, "open", "open")
    closed_dead, closed_unresolved = _world(tmp_path, "closed", "closed")

    assert open_unresolved == {_MOVES}
    assert open_dead == {_STAYS}
    assert closed_unresolved == frozenset()
    assert closed_dead == {_MOVES, _STAYS}

    moved = open_unresolved & closed_dead
    assert moved == {_MOVES}


def test_withdrawing_the_abstention_makes_the_open_world_answer_as_the_closed_one(
    tmp_path: Path,
) -> None:
    """The mutation, and it names the mechanism rather than moving a count.

    ``classify_liveness`` is called with no external reachability, so the one
    rule that separates the worlds is gone. The open world must then say
    exactly what the closed world says - same dead set, and nothing left in
    the abstention lane. A weaker reading, such as "one more symbol became
    dead", would also be satisfied by an unrelated rule going wrong.
    """

    closed_dead, closed_unresolved = _world(tmp_path, "closed-ref", "closed")
    mutated_dead, mutated_unresolved = _world(
        tmp_path, "open-mutant", "open", preamble=_WITHDRAW_THE_ABSTENTION
    )

    assert mutated_dead == closed_dead
    assert mutated_unresolved == closed_unresolved == frozenset()


def test_the_closed_world_does_not_depend_on_the_abstention_it_removed(
    tmp_path: Path,
) -> None:
    """Specificity control on the same causal path.

    If the mutation moved the closed world too, it would be perturbing the
    dead-code lane in general and the arm above would say nothing about the
    open/closed boundary in particular. The closed world has already dropped
    the unknown external consumer, so withdrawing the abstention must be inert
    there - and that is what makes the open world's collapse attributable.
    """

    reference = _world(tmp_path, "closed-clean", "closed")
    mutated = _world(
        tmp_path, "closed-mutant", "closed", preamble=_WITHDRAW_THE_ABSTENTION
    )

    assert mutated == reference
