# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A dead-code finding's REASON and its named witnesses must ride the cache.

``test_only_reference`` is the most useful thing this analyzer says about a
symbol and the most expensive to derive: the symbol is not unreferenced, it is
referenced only from tests, and the run can name which tests. That answer is
built from relationship facts, and on a warm run those facts come off the
cache wire rather than from the walk.

If the wire stops carrying them the symbol is still reported dead, still with
high confidence, still in the same lane - it just quietly changes its story
from "only your tests use this" to "nothing uses this", and drops the list of
tests that would have told the reader otherwise. A suite that reads the set of
dead qualnames sees nothing at all; both runs report the same two symbols.

So this module reads the ROWS, and it carries the mutation that makes the
reading mean something: the warm run is spawned with the cache's decode of
relationship facts neutralized, and the witness must then collapse. The same
mutation on a COLD run must be inert - that is what proves the arm is about
the cache path and not about the classifier.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from tests._liveness_report_helpers import (
    analysis_report,
    dead_code_family_of,
    dead_rows_by_qualname,
)

_SCOPE_ID: Final = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f4c"

#: Two private symbols, both dead in every world, differing ONLY in whether a
#: test references them. The pair is what makes the witness readable: an empty
#: ``test_reference_sources`` is the resting state of the field, so a mutant
#: that empties it is only visible next to a symbol whose list is populated.
_TREE: Final[dict[str, str]] = {
    "pkg/__init__.py": "\n",
    "pkg/_support.py": """
def only_tests_call_me(value: int) -> int:
    return value + 7


def never_referenced_at_all(value: int) -> int:
    return value - 1
""",
    "tests/__init__.py": "\n",
    "tests/test_support.py": """
from pkg._support import only_tests_call_me


def test_only_tests_call_me() -> None:
    assert only_tests_call_me(1) == 8
""",
}

_WITNESSED: Final = "pkg._support:only_tests_call_me"
_UNWITNESSED: Final = "pkg._support:never_referenced_at_all"
_TEST_WITNESS: Final = "tests.test_support:test_only_tests_call_me"

#: The mutation: the cache wire stops carrying the relationship facts the
#: witness is derived from. This is deliberately CACHE-specific - it touches
#: the decode path and nothing else - so a cold run cannot notice it, which is
#: the property the specificity control below relies on.
_CACHE_DROPS_RELATIONSHIP_FACTS: Final = (
    "import codeclone.cache._wire_decode as _wire_decode\n"
    "_wire_decode._decode_optional_wire_function_relationship_facts = (\n"
    "    lambda *args, **kwargs: ()\n"
    ")\n"
)


def _rows(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    return dead_rows_by_qualname(dead_code_family_of(payload))


def _witness(payload: dict[str, object], qualname: str) -> tuple[object, object]:
    """What this run says about a symbol, and on whose authority."""

    row = _rows(payload)[qualname]
    return row["reason"], row["test_reference_sources"]


def test_the_test_only_witness_survives_a_cache_round_trip(tmp_path: Path) -> None:
    """The law, over a run PROVEN warm rather than assumed warm.

    ``expect_warm_cache`` asserts the hit count, not merely that a cache file
    was opened: a run can load a cache and re-analyze every file in it, and
    such a run would satisfy this pin while exercising nothing.
    """

    cold = analysis_report(tmp_path, _TREE, "witness", scope_id=_SCOPE_ID)
    warm = analysis_report(
        tmp_path, _TREE, "witness", scope_id=_SCOPE_ID, expect_warm_cache=True
    )

    # Population witness: the reason and the list are both non-empty, so there
    # is something for a warm run to lose.
    assert _witness(cold, _WITNESSED) == ("test_only_reference", [_TEST_WITNESS])
    # Contrast: the sibling's empty list is the field's resting state.
    assert _witness(cold, _UNWITNESSED) == ("unreferenced", [])

    assert _rows(warm) == _rows(cold)


def test_a_cache_that_drops_the_relationship_facts_collapses_the_witness(
    tmp_path: Path,
) -> None:
    """The mutation, so the pin above is known to be capable of failing.

    With the wire's decode of relationship facts neutralized, the warm run
    still calls the same two symbols dead - the set of qualnames does not move
    at all - and the one that only tests call silently becomes a symbol
    nothing references. That is the exact shape of the regression the pin
    exists to catch, and it is invisible to any assertion about the lane.
    """

    analysis_report(tmp_path, _TREE, "mutant", scope_id=_SCOPE_ID)
    warm = analysis_report(
        tmp_path,
        _TREE,
        "mutant",
        scope_id=_SCOPE_ID,
        expect_warm_cache=True,
        preamble=_CACHE_DROPS_RELATIONSHIP_FACTS,
    )

    assert _witness(warm, _WITNESSED) == ("unreferenced", [])
    assert set(_rows(warm)) == {_WITNESSED, _UNWITNESSED}, (
        "the mutant moved the dead lane as well, so the collapse above is not "
        "a statement about the witness alone"
    )


def test_the_same_mutation_is_inert_on_a_cold_run(tmp_path: Path) -> None:
    """Specificity control: the mutation acts on the CACHE, not the classifier.

    A mutation that also broke a cold run would prove the witness can be
    destroyed, but not that the CACHE is what carries it - and this module
    claims the second thing. A cold run derives the facts from the walk and
    never decodes them, so the identical preamble must change nothing.
    """

    clean = analysis_report(tmp_path, _TREE, "cold-clean", scope_id=_SCOPE_ID)
    mutated = analysis_report(
        tmp_path,
        _TREE,
        "cold-mutant",
        scope_id=_SCOPE_ID,
        preamble=_CACHE_DROPS_RELATIONSHIP_FACTS,
    )

    assert _witness(mutated, _WITNESSED) == ("test_only_reference", [_TEST_WITNESS])
    assert _rows(mutated) == _rows(clean)
