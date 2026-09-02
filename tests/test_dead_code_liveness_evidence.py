# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""A liveness reason must name what actually holds the symbol live.

The verdict lane and the evidence lane answer two different questions. "Is
this symbol live?" is the verdict; "what holds it live?" is the evidence. A
falsificatory corpus measured the second one wrong while the first was right:
six of sixteen ``export_root`` reasons were attached to members that have an
ordinary internal call site, and one symbol drew ``external_decorator`` from
its own ``@overload`` stubs. Both readings survive because nothing downstream
re-checks a reason - it is recorded, exported and believed.

These pins hold the evidence layer to the same standard as the verdict:

* a member an internal call already holds live is not given an export root,
  and does not depend on one (the two directions live in separate tests);
* a member nothing else holds live IS given one, and genuinely depends on it;
* a symbol's own ``@overload`` stubs never vote for its liveness.

The report-layer pins spawn the CLI rather than importing it: these are
statements about what a user reads, and they must break if the wiring between
the owner and the report breaks, not only if the owner does.
"""

from __future__ import annotations

from pathlib import Path

from codeclone.metrics.dead_code import classify_liveness
from codeclone.metrics.external_reachability import collect_external_reachability
from codeclone.models import DeadCandidate, ExternalReachability, ModuleDep
from tests._liveness_report_helpers import (
    dead_code_family,
    dead_qualnames,
    live_root_reason_by_qualname,
    unresolved_by_qualname,
)

#: Baseline update and gating both require a stable canonical scope id.
_SCOPE_ID = "0192f3aa-6c51-7b28-9d44-1ea5c07b6f40"

#: The measured shape. ``Service.refresh`` has an ordinary attribute call site
#: inside the package; ``Service.render`` has none. Both belong to a class the
#: package re-exports, so the export-root rule reaches both - and only one of
#: them is actually held live by the export.
_CALLED_AND_EXPORTED_TREE = {
    "pkg/__init__.py": """
from .api import Service
from .entry import run

__all__ = ["Service", "run"]
""",
    "pkg/api.py": """
class Service:
    def render(self) -> int:
        return 1

    def refresh(self) -> int:
        return 2
""",
    "pkg/entry.py": """
from .api import Service


def run() -> int:
    return Service().refresh()
""",
}

#: ``@overload`` stubs declare a signature; they are not a caller. The
#: implementation below them has an ordinary call site, which is the whole of
#: this symbol's claim to life.
_OVERLOAD_TREE = {
    "pkg/__init__.py": """
from .entry import run

__all__ = ["run"]
""",
    "pkg/internal.py": """
from typing import overload


class Holder:
    @overload
    def combine(self, value: int) -> int: ...

    @overload
    def combine(self, value: str) -> str: ...

    def combine(self, value):
        return value
""",
    "pkg/entry.py": """
from .internal import Holder


def run() -> int:
    return Holder().combine(9)
""",
}


def test_a_called_member_gets_no_record_while_its_uncalled_sibling_is_unresolved(
    tmp_path: Path,
) -> None:
    """Report layer, direction A: a call site is the reason, not the export.

    ``Service.refresh`` is called as ``Service().refresh()`` and gets no record
    in either lane. ``Service.render`` is uncalled and reachable, so it gets an
    unresolved record - and no lane spells ``export_root``, which used to read
    as "live because exported" where the truth was "live because called".
    """

    family = dead_code_family(
        tmp_path,
        _CALLED_AND_EXPORTED_TREE,
        "called-and-exported",
        scope_id=_SCOPE_ID,
    )
    reasons = live_root_reason_by_qualname(family)
    unresolved = unresolved_by_qualname(family)

    # Reachability of the guard: the reachability rule DID run on this tree
    # and did reach the member nothing else holds live - as an unresolved
    # record, never as a live root. A pin that only asserted an absence would
    # also pass on a tree the rule never reached.
    assert "export_root" not in set(reasons.values())
    assert unresolved["pkg.api:Service.render"]["witness"] == "public_module:pkg.api"
    assert "pkg.api:Service.refresh" not in unresolved
    assert "pkg.api:Service.refresh" not in reasons
    assert "pkg.api:Service.refresh" not in dead_qualnames(family)


def test_overload_stubs_do_not_root_their_own_symbol(tmp_path: Path) -> None:
    """Report layer: ``@overload`` is a declaration, never a caller.

    ``typing.overload`` resolves through an external module alias, so the
    stub's decorator looked exactly like a framework registration and rooted
    the symbol it declares. The implementation's real call site is the only
    evidence there is.
    """

    family = dead_code_family(tmp_path, _OVERLOAD_TREE, "overload", scope_id=_SCOPE_ID)
    reasons = live_root_reason_by_qualname(family)

    assert "pkg.internal:Holder.combine" not in reasons
    assert "pkg.internal:Holder.combine" not in dead_qualnames(family)


def _candidate(qualname: str, *, kind: str = "method") -> DeadCandidate:
    module, _, local = qualname.partition(":")
    return DeadCandidate(
        qualname=qualname,
        # The walk stores the BARE name here, which is the whole reason an
        # attribute call reaches liveness as a name and not as a qualname.
        local_name=local.rpartition(".")[2],
        filepath=f"{module.replace('.', '/')}.py",
        start_line=1,
        end_line=2,
        kind=kind,  # type: ignore[arg-type]
    )


#: A PRIVATE api module: its class reaches the world only through the package
#: re-export edge, which is what makes that edge the causal construct below.
_API_MODULE = "distillations._api"
_PACKAGE_MODULE = "distillations"


def _liveness_inputs() -> tuple[
    tuple[ModuleDep, ...],
    tuple[DeadCandidate, ...],
    frozenset[str],
    frozenset[str],
]:
    """One population, two members: one called, one not.

    ``Service`` is on the package export chain. ``Service.refresh`` carries an
    ordinary attribute call, which reaches the liveness decision as a bare name
    in ``referenced_names`` - never as a qualname. ``Service.render`` carries
    nothing.
    """

    module_deps = (
        ModuleDep(
            source=_PACKAGE_MODULE,
            target=_API_MODULE,
            import_type="from_import",
            line=1,
            resolution="analyzed",
            requested_names=("Service",),
        ),
    )
    candidates = (
        _candidate(f"{_API_MODULE}:Service", kind="class"),
        _candidate(f"{_API_MODULE}:Service.render"),
        _candidate(f"{_API_MODULE}:Service.refresh"),
    )
    referenced_qualnames = frozenset({f"{_API_MODULE}:Service"})
    referenced_names = frozenset({"Service", "refresh"})
    return module_deps, candidates, referenced_qualnames, referenced_names


def _reachability(
    module_deps: tuple[ModuleDep, ...],
    candidates: tuple[DeadCandidate, ...],
) -> dict[str, ExternalReachability]:
    return {
        row.qualname: row
        for row in collect_external_reachability(
            dead_candidates=candidates,
            module_deps=module_deps,
            class_metrics=(),
            package_modules=frozenset({_PACKAGE_MODULE}),
        )
    }


def _edge_rows() -> tuple[
    tuple[DeadCandidate, ...],
    dict[str, ExternalReachability],
    frozenset[str],
    frozenset[str],
]:
    """The population with its re-export edge, resolved: candidates, rows,
    referenced qualnames, referenced names."""

    module_deps, candidates, referenced_qualnames, referenced_names = _liveness_inputs()
    return (
        candidates,
        _reachability(module_deps, candidates),
        referenced_qualnames,
        referenced_names,
    )


def _open_world_lanes(
    candidates: tuple[DeadCandidate, ...],
    rows: dict[str, ExternalReachability],
    *,
    referenced_names: frozenset[str],
    referenced_qualnames: frozenset[str],
) -> tuple[set[str], set[str]]:
    """The dead and unresolved qualnames the evaluator utters under ``open``."""

    classification = classify_liveness(
        definitions=candidates,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
        external_reachability=tuple(rows.values()),
        world_contract="open",
    )
    return (
        {item.qualname for item in classification.dead_items},
        {item.qualname for item in classification.unresolved_reachability},
    )


def test_reachability_is_evidence_for_every_member_called_or_not() -> None:
    """Direction A, the layering: reachability does not read liveness.

    Both members are reachable through the same edge. The called one is live
    for its own reason and the evaluator never consults its reachability; the
    fact still exists, because one symbol may carry both facts.
    """

    candidates, rows, referenced_qualnames, referenced_names = _edge_rows()
    render, refresh = f"{_API_MODULE}:Service.render", f"{_API_MODULE}:Service.refresh"

    assert {name: rows[name].state for name in (render, refresh)} == {
        render: "reachable",
        refresh: "reachable",
    }
    assert rows[render].witness == "package_reexport:distillations"

    dead, unresolved = _open_world_lanes(
        candidates,
        rows,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
    )
    assert f"{_API_MODULE}:Service.render" in unresolved
    assert f"{_API_MODULE}:Service.refresh" not in unresolved
    assert f"{_API_MODULE}:Service.refresh" not in dead


def test_a_called_member_stays_live_when_the_reachability_evidence_is_removed() -> None:
    """Direction A, the causal independence: the call site carries it alone."""

    _, candidates, referenced_qualnames, referenced_names = _liveness_inputs()

    without_evidence = classify_liveness(
        definitions=candidates,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
        world_contract="open",
    )

    dead = {item.qualname for item in without_evidence.dead_items}
    assert f"{_API_MODULE}:Service.refresh" not in dead
    # The same run must still be able to call something dead, or "not in dead"
    # is a statement about an empty set.
    assert f"{_API_MODULE}:Service.render" in dead
    assert without_evidence.unresolved_reachability == ()


def test_an_uncalled_exported_member_depends_on_the_reexport_edge() -> None:
    """Direction B, the causal pin on EVIDENCE (RULING 2026-09-01 §1).

    Remove the package re-export edge and ``ExternalReachability(render)``
    itself moves from ``reachable`` to ``not_reachable``; the verdict follows
    from that fact and only from it. Asserting only the verdict would let the
    world contract stand in for the defect.
    """

    candidates, with_edge, _, _ = _edge_rows()
    without_edge = _reachability((), candidates)
    render = f"{_API_MODULE}:Service.render"

    assert (
        with_edge[render].state,
        without_edge[render].state,
        without_edge[render].witness,
    ) == ("reachable", "not_reachable", "")

    verdicts = {
        label: _open_world_lanes(
            candidates,
            rows,
            referenced_names=frozenset(),
            referenced_qualnames=frozenset({f"{_API_MODULE}:Service"}),
        )[0]
        for label, rows in (("with_edge", with_edge), ("without_edge", without_edge))
    }
    assert f"{_API_MODULE}:Service.render" not in verdicts["with_edge"]
    assert f"{_API_MODULE}:Service.render" in verdicts["without_edge"]
