# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The dead-code wire under the world contract (RULING 2026-09-01, §4-§6).

Three symbols that used to be indistinguishable on the wire:

    A  internally live                                   -> no record at all
    B  externally reachable, no internal evidence, open  -> ``unresolved`` row
    C  truly dead under any world                        -> ``dead`` finding

Before this wave B either looked like A (an ``export_root`` held it live) or
like C (a high-confidence dead finding on live public API). Both readings were
the same wire saying two different things, and the ruling's acceptance test is
that B is now a third, distinguishable statement - on the JSON a user reads,
from a SPAWNED CLI, behind the witness chain.
"""

from __future__ import annotations

from pathlib import Path

from codeclone.contracts import REPORT_SCHEMA_VERSION
from codeclone.utils.run_identity import report_run_identity
from tests._liveness_report_helpers import (
    analysis_report,
    dead_code_family,
    dead_code_family_of,
    dead_qualnames,
    live_root_reason_by_qualname,
    run_cli,
    unresolved_by_qualname,
)

_SCOPE_ID = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f3a"

#: ``Client`` is re-exported by the package and held live by that import.
#: ``Client.post`` is public and uncalled (B). ``Client._render`` is called
#: from ``post`` (A). ``_helper`` and ``_local`` are private and uncalled (C).
#: ``build`` is a public function of a public module, uncalled (B).
_ABC_TREE = {
    "pkg/__init__.py": """
from ._impl import Client

__all__ = ["Client"]
""",
    "pkg/_impl.py": """
class Client:
    def post(self, url: str) -> str:
        return self._render(url)

    def _render(self, url: str) -> str:
        return url


def _helper() -> int:
    return 1
""",
    "pkg/service.py": """
from ._impl import Client


def build() -> Client:
    return Client()


def _local() -> int:
    return 2
""",
}

_B_ROWS = {"pkg._impl:Client.post", "pkg.service:build"}
_C_ROWS = {"pkg._impl:_helper", "pkg.service:_local"}


def test_the_wire_tells_a_b_and_c_apart_under_the_open_world(
    tmp_path: Path,
) -> None:
    payload = analysis_report(tmp_path, _ABC_TREE, "abc-open", scope_id=_SCOPE_ID)
    family = dead_code_family_of(payload)

    dead = dead_qualnames(family)
    unresolved = unresolved_by_qualname(family)

    # C: dead findings, and only those.
    assert dead == _C_ROWS
    # B: the sibling lane, and only those.
    assert set(unresolved) == _B_ROWS
    # A: neither lane.
    assert {"pkg._impl:Client._render", "pkg._impl:Client"}.isdisjoint(
        dead | set(unresolved)
    )

    post = unresolved["pkg._impl:Client.post"]
    assert {
        key: post[key]
        for key in ("reason", "reachability", "witness", "world_contract", "kind")
    } == {
        "reason": "externally_reachable",
        "reachability": "reachable",
        "witness": "package_reexport:pkg",
        "world_contract": "open",
        "kind": "method",
    }
    assert post["relative_path"] == "pkg/_impl.py"
    start_line, end_line = post["start_line"], post["end_line"]
    assert isinstance(start_line, int) and isinstance(end_line, int)
    assert 0 < start_line < end_line
    build = unresolved["pkg.service:build"]
    assert build["witness"] == "public_module:pkg.service"
    assert build["kind"] == "function"


def test_the_open_world_summary_names_the_lane_the_world_and_the_schema(
    tmp_path: Path,
) -> None:
    payload = analysis_report(tmp_path, _ABC_TREE, "abc-summary", scope_id=_SCOPE_ID)
    family = dead_code_family_of(payload)

    summary = family["summary"]
    assert isinstance(summary, dict)
    assert {
        key: summary[key]
        for key in ("unresolved", "world_contract", "total", "high_confidence")
    } == {"unresolved": 2, "world_contract": "open", "total": 2, "high_confidence": 2}

    # The export chain is reachability evidence now, never a live root.
    assert "export_root" not in set(live_root_reason_by_qualname(family).values())

    assert payload["report_schema_version"] == REPORT_SCHEMA_VERSION == "3.3"


def test_the_closed_world_calls_b_dead_from_the_cli_flag(tmp_path: Path) -> None:
    family = dead_code_family(
        tmp_path,
        _ABC_TREE,
        "abc-closed-flag",
        scope_id=_SCOPE_ID,
        cli_args=("--dead-code-world", "closed"),
    )

    assert dead_qualnames(family) == _B_ROWS | _C_ROWS
    assert unresolved_by_qualname(family) == {}
    summary = family["summary"]
    assert isinstance(summary, dict)
    assert summary["unresolved"] == 0
    assert summary["world_contract"] == "closed"


def test_the_closed_world_calls_b_dead_from_pyproject(tmp_path: Path) -> None:
    """The enforcement witness for the pyproject key: config owner -> verdict."""

    family = dead_code_family(
        tmp_path,
        _ABC_TREE,
        "abc-closed-pyproject",
        scope_id=_SCOPE_ID,
        pyproject_lines=('dead_code_world = "closed"',),
    )

    assert dead_qualnames(family) == _B_ROWS | _C_ROWS
    summary = family["summary"]
    assert isinstance(summary, dict)
    assert summary["world_contract"] == "closed"


def test_the_world_contract_names_the_run(tmp_path: Path) -> None:
    """Two reports over one tree that differ only in the world contract utter
    different verdicts, so they may not share a run identity."""

    open_payload = analysis_report(tmp_path, _ABC_TREE, "id-open", scope_id=_SCOPE_ID)
    closed_payload = analysis_report(
        tmp_path,
        _ABC_TREE,
        "id-closed",
        scope_id=_SCOPE_ID,
        cli_args=("--dead-code-world", "closed"),
    )

    assert report_run_identity(open_payload) != report_run_identity(closed_payload)


def test_the_unresolved_lane_survives_a_warm_cache(tmp_path: Path) -> None:
    """Reachability is computed from facts that already ride the cache wire,
    so a warm run must utter exactly the cold run's lanes."""

    cold = dead_code_family(tmp_path, _ABC_TREE, "abc-warm", scope_id=_SCOPE_ID)
    warm = dead_code_family(
        tmp_path,
        _ABC_TREE,
        "abc-warm",
        scope_id=_SCOPE_ID,
        expect_warm_cache=True,
    )

    assert unresolved_by_qualname(warm) == unresolved_by_qualname(cold)
    assert dead_qualnames(warm) == dead_qualnames(cold)
    assert set(unresolved_by_qualname(cold)) == _B_ROWS


def test_an_unknown_world_contract_is_refused(tmp_path: Path) -> None:
    completed = run_cli(
        tmp_path,
        _ABC_TREE,
        "abc-bad-world",
        scope_id=_SCOPE_ID,
        cli_args=("--dead-code-world", "sideways"),
    )

    # A contract error, on the CLI's own status stream (stdout), naming the
    # key and the accepted vocabulary - so a build that merely rejects the flag
    # as unknown does not pass this pin by accident.
    assert completed.returncode != 0
    output = completed.stdout + completed.stderr
    assert "CONTRACT ERROR" in output
    assert "dead_code_world" in output
    assert "open" in output and "closed" in output
