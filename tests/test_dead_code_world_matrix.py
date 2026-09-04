# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The open/closed liveness matrix, as an executable law rather than prose.

Three kinds of support a symbol can have, and what each world contract may
conclude from it:

    support                                  open          closed
    ---------------------------------------  ------------  ------------
    proven internal use                      LIVE          LIVE
    unknown external reachability, no use    UNRESOLVED    DEAD
    ambiguous internal bare-name support     UNRESOLVED    UNRESOLVED

The third row is the load-bearing one, and it is a statement about the
FUTURE. The closed world removes the unknown EXTERNAL consumer; it does not
turn a bad INTERNAL binding into proof of absence. A bare name is not
symbol-specific evidence - popular names like ``get``, ``save`` or ``close``
would revive half a project through an unrelated receiver - so a symbol whose
only support is a bare-name match is not proven live in either world.

Today the bare-name fallback still grants LIVE. That is what the bare-name
authority criterion changes, and it is not this suite's work: it carries its
own blind external benchmark because it moves a user-facing verdict on a
measured 4513 symbols in this repository alone. So row 3 is pinned as
``xfail(strict=True)``: it states the law now, it fails loudly the day the
law is satisfied, and the XPASS is the signal to delete the marker rather
than to discover the row was never pinned at all.

Each row is CAUSAL, not asserted: every fixture is paired with a control
that differs only in the mechanism the row names, and the control's verdict
proves that mechanism - and not the module layout, the name or the file - is
what put the fixture in its row.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._liveness_report_helpers import (
    VERDICT_DEAD,
    VERDICT_LIVE,
    VERDICT_UNRESOLVED,
    analysis_report,
    liveness_verdict,
)

_SCOPE_ID = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f41"

#: One tree carrying a member of every row, each beside a control that
#: differs ONLY in the support the row is about.
#:
#: * ``pkg.core`` is a public module, so everything in it is externally
#:   reachable and row 1 and row 2 differ only in the internal call.
#: * ``pkg._support`` is private, so nothing in it is externally reachable
#:   and row 3 and its control differ only in the bare-name reference.
_MATRIX_TREE = {
    "pkg/__init__.py": "",
    "pkg/core.py": """
def row1_proven_internal_use() -> int:
    return 1


def row2_unknown_external_reach() -> int:
    return 2
""",
    "pkg/entry.py": """
from typing import Any

from .core import row1_proven_internal_use


def call_row1() -> int:
    return row1_proven_internal_use()


def touch_bare_name(obj: Any) -> int:
    return obj.row3_ambiguous_bare_name()
""",
    "pkg/_support.py": """
def row3_ambiguous_bare_name() -> int:
    return 3


def control_no_support_at_all() -> int:
    return 4
""",
}

_ROW1 = "pkg.core:row1_proven_internal_use"
_ROW2 = "pkg.core:row2_unknown_external_reach"
_ROW3 = "pkg._support:row3_ambiguous_bare_name"
_CONTROL_UNSUPPORTED = "pkg._support:control_no_support_at_all"

#: The law. One cell per (row, world); nothing else in this module decides a
#: verdict, so flipping a cell can only red the row it belongs to.
_MATRIX: dict[str, dict[str, str]] = {
    _ROW1: {"open": VERDICT_LIVE, "closed": VERDICT_LIVE},
    _ROW2: {"open": VERDICT_UNRESOLVED, "closed": VERDICT_DEAD},
    _ROW3: {"open": VERDICT_UNRESOLVED, "closed": VERDICT_UNRESOLVED},
}

#: Row 3 is the future. Naming the criterion here rather than in a comment
#: means the exit condition travels with the marker.
_ROW3_EXIT = (
    "bare-name authority (criterion C): a bare-name match is not "
    "symbol-specific evidence and must abstain in BOTH worlds. Delete this "
    "marker when C lands - the strict XPASS is the signal."
)

_ROWS = pytest.mark.parametrize(
    "qualname",
    [
        pytest.param(_ROW1, id="row1-proven-internal-use"),
        pytest.param(_ROW2, id="row2-unknown-external-reachability"),
        pytest.param(
            _ROW3,
            id="row3-ambiguous-bare-name",
            marks=pytest.mark.xfail(strict=True, reason=_ROW3_EXIT),
        ),
    ],
)


@pytest.fixture(scope="module")
def matrix_reports(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, dict[str, object]]:
    """One report per world over the one tree, behind the witness chain."""

    root = tmp_path_factory.mktemp("matrix")
    return {
        "open": analysis_report(root, _MATRIX_TREE, "matrix-open", scope_id=_SCOPE_ID),
        "closed": analysis_report(
            root,
            _MATRIX_TREE,
            "matrix-closed",
            scope_id=_SCOPE_ID,
            cli_args=("--dead-code-world", "closed"),
        ),
    }


@_ROWS
def test_the_matrix_row_holds_under_both_world_contracts(
    matrix_reports: dict[str, dict[str, object]],
    qualname: str,
) -> None:
    """One row of the law, read from a spawned run of each world."""

    verdicts = {
        world: liveness_verdict(matrix_reports[world], qualname)
        for world in ("open", "closed")
    }
    assert verdicts == _MATRIX[qualname]


def test_row1_is_live_because_of_the_internal_call_and_not_its_module(
    matrix_reports: dict[str, dict[str, object]],
    tmp_path: Path,
) -> None:
    """Positive control on row 1's own causal path.

    ``row1_proven_internal_use`` and ``row2_unknown_external_reach`` are
    siblings in the same public module. Removing the ONE call site moves the
    first onto the second's row in both worlds, which is what proves the
    call - not the module, the name or the file - is the row-1 mechanism.
    """

    for world in ("open", "closed"):
        assert liveness_verdict(matrix_reports[world], _ROW1) == VERDICT_LIVE

    without_call = dict(_MATRIX_TREE)
    without_call["pkg/entry.py"] = """
from typing import Any


def touch_bare_name(obj: Any) -> int:
    return obj.row3_ambiguous_bare_name()
"""
    for world, expected in (("open", VERDICT_UNRESOLVED), ("closed", VERDICT_DEAD)):
        payload = analysis_report(
            tmp_path,
            without_call,
            f"row1-control-{world}",
            scope_id=_SCOPE_ID,
            cli_args=() if world == "open" else ("--dead-code-world", "closed"),
        )
        assert liveness_verdict(payload, _ROW1) == expected


def test_row3_is_live_today_because_of_the_bare_name_and_nothing_else(
    matrix_reports: dict[str, dict[str, object]],
    tmp_path: Path,
) -> None:
    """Positive control on row 3's own causal path, and its population witness.

    ``row3_ambiguous_bare_name`` and ``control_no_support_at_all`` are
    siblings in the same PRIVATE module, so neither is externally reachable
    and the reachability lane cannot be what separates them. The control is
    dead in both worlds; the fixture is not; removing the single ambiguous
    attribute call collapses the fixture onto the control.

    This test deliberately does NOT assert the law - it asserts the current
    behaviour the law contradicts, so that the row-3 strict xfail above is
    known to be xfailing for the measured reason and not for a typo.
    """

    for world in ("open", "closed"):
        assert liveness_verdict(matrix_reports[world], _CONTROL_UNSUPPORTED) == (
            VERDICT_DEAD
        )
        assert liveness_verdict(matrix_reports[world], _ROW3) == VERDICT_LIVE

    without_bare_name = dict(_MATRIX_TREE)
    without_bare_name["pkg/entry.py"] = """
from .core import row1_proven_internal_use


def call_row1() -> int:
    return row1_proven_internal_use()
"""
    for world in ("open", "closed"):
        payload = analysis_report(
            tmp_path,
            without_bare_name,
            f"row3-control-{world}",
            scope_id=_SCOPE_ID,
            cli_args=() if world == "open" else ("--dead-code-world", "closed"),
        )
        assert liveness_verdict(payload, _ROW3) == VERDICT_DEAD


def test_the_matrix_covers_every_row_exactly_once() -> None:
    """The table and the parametrisation are one list, not two that drift."""

    assert set(_MATRIX) == {_ROW1, _ROW2, _ROW3}
    assert all(set(cells) == {"open", "closed"} for cells in _MATRIX.values())
