# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Every abstention says what prevents the proof, and says it in vocabulary.

A verdict a consumer cannot interrogate is a verdict they must take on
faith. The dead lane has been held to that standard since the test-only
reason shipped: ``DeadItem`` refuses ``test_only_reference`` with no named
test, and refuses named tests under ``unreferenced``, so the reason and the
evidence can never disagree.

The UNRESOLVED lane had no such door. Its producer has always written a
witness - measured on this repository, all 79 rows carry one - but nothing
held it to that, so the one thing this lane exists to say could have gone
missing without a single test noticing. An abstention with no witness is
strictly worse than a finding: it reports that CodeClone declined to decide
and then declines to say why.

Three things are refused here, and the third is the one that survives a
careless fix:

* an empty witness - the gap named directly;
* a witness naming no declared exposure mechanism, which is a string, not a
  witness;
* a witness whose mechanism CANNOT explain the state it rides with - a
  ``public_module`` witness under ``reachability_unresolved`` says "here is
  the public path" where the row says "no path could be read". Refusing the
  empty witness alone would accept that row, and it is the shape a
  well-meaning "always put something in the witness" fix produces.

``reachability_unresolved`` has ZERO members in this repository: every one
of its 79 unresolved rows is ``externally_reachable`` through a public
module. An empty population is not a pass, so the synthetic member below is
constructed to fall in it, and the report-level pin reads its witness.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codeclone.models import (
    EXPOSURE_MECHANISM_STATES,
    EXTERNAL_EXPOSURE_MECHANISMS,
    LivenessVocabularyError,
    UnresolvedReachabilityItem,
    witness_mechanism,
)
from tests._liveness_report_helpers import (
    analysis_report,
    dead_code_family_of,
    unresolved_by_qualname,
)

_SCOPE_ID = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f42"

#: A tree with a member of each unresolved reason.
#:
#: ``pkg.public:reachable_symbol`` is a public module's uncalled function:
#: reachable, and the witness is the public path a consumer would spell.
#: ``pkg._served:served_symbol`` sits under a package whose namespace is
#: built by a module-level ``__getattr__`` (PEP 562), so what the package
#: serves cannot be read statically and the witness is that construct.
_BOTH_REASONS_TREE = {
    "pkg/__init__.py": """
from typing import Any

__all__ = ["served_symbol"]


def __getattr__(name: str) -> Any:
    from . import _served

    return getattr(_served, name)
""",
    "pkg/_served.py": """
def served_symbol() -> int:
    return 1


def unreachable_here() -> int:
    return 2
""",
    "pkg/public.py": """
def reachable_symbol() -> int:
    return 3
""",
}

_REACHABLE_ROW = "pkg.public:reachable_symbol"
_UNRESOLVED_ROW = "pkg._served:served_symbol"

#: Which reason each reachability state may carry. The lane is an
#: abstention, so ``not_reachable`` is absent by construction: a symbol
#: nothing outside can reach has no reason to be here at all.
_REASON_OF_STATE = {
    "reachable": "externally_reachable",
    "unresolved": "reachability_unresolved",
}


@pytest.fixture(scope="module")
def both_reasons_family(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, object]:
    root = tmp_path_factory.mktemp("witness")
    payload = analysis_report(
        root,
        _BOTH_REASONS_TREE,
        "witness-open",
        scope_id=_SCOPE_ID,
    )
    return dead_code_family_of(payload)


def test_every_unresolved_row_carries_a_reason_and_a_mechanism_witness(
    both_reasons_family: dict[str, object],
) -> None:
    """The report-level statement: no abstention without an explanation.

    Both reasons are asserted PRESENT before the loop. A loop over rows is a
    vacuous pass on an empty list, and one over rows that all share a reason
    is a vacuous pass on the reason it never saw.
    """

    rows = unresolved_by_qualname(both_reasons_family)
    reasons = {qualname: row["reason"] for qualname, row in rows.items()}
    assert reasons[_REACHABLE_ROW] == "externally_reachable"
    assert reasons[_UNRESOLVED_ROW] == "reachability_unresolved"

    for qualname, row in sorted(rows.items()):
        witness = row["witness"]
        assert isinstance(witness, str) and witness, (
            f"{qualname} abstains with no witness: {row}"
        )
        mechanism = witness_mechanism(witness)
        assert mechanism is not None, (
            f"{qualname} witness {witness!r} names no declared mechanism"
        )
        state = row["reachability"]
        assert state in EXPOSURE_MECHANISM_STATES[mechanism], (
            f"{qualname} witness {witness!r} cannot explain state {state!r}"
        )
        assert _REASON_OF_STATE[str(state)] == row["reason"]


def test_the_unresolved_witness_names_the_construct_that_prevents_the_proof(
    both_reasons_family: dict[str, object],
) -> None:
    """The synthetic member of the empty population, read whole.

    ``module_getattr:pkg`` is the answer to "what prevents the proof": the
    package serves names through a hook the walk cannot read, so no static
    read settles what it exposes. A row that merely said ``unresolved`` with
    a location would leave the user exactly where the ruling found them.
    """

    row = unresolved_by_qualname(both_reasons_family)[_UNRESOLVED_ROW]
    assert {
        key: row[key] for key in ("reason", "reachability", "witness", "world_contract")
    } == {
        "reason": "reachability_unresolved",
        "reachability": "unresolved",
        "witness": "module_getattr:pkg",
        "world_contract": "open",
    }


def test_the_closed_world_calls_the_unreadable_namespace_dead(
    tmp_path: Path,
) -> None:
    """The population witness for the row above: it is a real matrix row 2.

    Under the closed world the unknown external consumer is gone, so the
    same symbol is dead - which is what makes the open-world abstention a
    verdict about the world and not about the symbol.
    """

    payload = analysis_report(
        tmp_path,
        _BOTH_REASONS_TREE,
        "witness-closed",
        scope_id=_SCOPE_ID,
        cli_args=("--dead-code-world", "closed"),
    )
    family = dead_code_family_of(payload)
    items = family["items"]
    assert isinstance(items, list)
    assert _UNRESOLVED_ROW in {str(item["qualname"]) for item in items}
    assert unresolved_by_qualname(family) == {}


def test_an_unresolved_row_without_a_witness_is_refused() -> None:
    """The gap, named directly and closed at the type."""

    with pytest.raises(LivenessVocabularyError, match="no witness"):
        UnresolvedReachabilityItem(
            qualname="pkg.mod:symbol",
            filepath="pkg/mod.py",
            start_line=1,
            end_line=2,
            kind="function",
            reachability="unresolved",
            witness="",
            world_contract="open",
            reason="reachability_unresolved",
        )


def test_a_witness_naming_no_declared_mechanism_is_refused() -> None:
    """A free-form string is not a witness, however plausible it reads."""

    with pytest.raises(LivenessVocabularyError, match="unknown external exposure"):
        UnresolvedReachabilityItem(
            qualname="pkg.mod:symbol",
            filepath="pkg/mod.py",
            start_line=1,
            end_line=2,
            kind="function",
            reachability="unresolved",
            witness="probably_dynamic:pkg",
            world_contract="open",
            reason="reachability_unresolved",
        )


def test_a_witness_that_cannot_explain_its_state_is_refused() -> None:
    """The opposite boundary: present, declared, and about the wrong thing.

    ``public_module`` witnesses a PROVEN public path. Riding it on a row
    that says no path could be read is the failure a witness-presence check
    alone cannot see, and it is what "always fill in the witness" produces.
    """

    with pytest.raises(LivenessVocabularyError, match="cannot witness"):
        UnresolvedReachabilityItem(
            qualname="pkg.mod:symbol",
            filepath="pkg/mod.py",
            start_line=1,
            end_line=2,
            kind="function",
            reachability="unresolved",
            witness="public_module:pkg.mod",
            world_contract="open",
            reason="reachability_unresolved",
        )


def test_a_reason_that_contradicts_its_state_is_refused() -> None:
    """The typed reason is derived from the state; it may not disagree."""

    with pytest.raises(LivenessVocabularyError, match="reason"):
        UnresolvedReachabilityItem(
            qualname="pkg.mod:symbol",
            filepath="pkg/mod.py",
            start_line=1,
            end_line=2,
            kind="function",
            reachability="reachable",
            witness="public_module:pkg.mod",
            world_contract="open",
            reason="reachability_unresolved",
        )


def test_a_symbol_nothing_can_reach_never_enters_the_abstention_lane() -> None:
    """``not_reachable`` is a verdict, not an abstention."""

    with pytest.raises(LivenessVocabularyError, match="not_reachable"):
        UnresolvedReachabilityItem(
            qualname="pkg.mod:symbol",
            filepath="pkg/mod.py",
            start_line=1,
            end_line=2,
            kind="function",
            reachability="not_reachable",
            witness="public_module:pkg.mod",
            world_contract="open",
            reason="externally_reachable",
        )


def test_every_declared_exposure_mechanism_is_classified() -> None:
    """The relation cannot silently miss a mechanism added later.

    Without this, a new exposure mechanism would reach a consumer through a
    ``KeyError`` at the first row that carried it, or - worse, if the lookup
    were ever made forgiving - through a row nothing checked at all.

    Each entry is a NON-EMPTY set of states the abstention lane can carry.
    Empty would be a mechanism no row may ever use, which is a retirement and
    belongs in the park list, not here; and ``not_reachable`` is refused
    because that state is a verdict and never enters this lane at all.
    """

    assert set(EXPOSURE_MECHANISM_STATES) == set(EXTERNAL_EXPOSURE_MECHANISMS)
    for mechanism, states in sorted(EXPOSURE_MECHANISM_STATES.items()):
        assert states, f"{mechanism} witnesses no state at all"
        assert states <= {"reachable", "unresolved"}, (mechanism, sorted(states))
