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

from codeclone.core import entrypoints as entrypoints_mod
from codeclone.metrics.dead_code import classify_liveness
from codeclone.models import ClassMetrics, DeadCandidate, ModuleDep
from tests._ast_metrics_helpers import build_test_module_registry
from tests._liveness_report_helpers import (
    dead_code_family,
    dead_qualnames,
    live_root_reason_by_qualname,
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


def test_export_root_is_not_the_recorded_reason_for_a_called_member(
    tmp_path: Path,
) -> None:
    """Report layer, direction A: a call site is the reason, not the export.

    ``Service.refresh`` is called as ``Service().refresh()``. The export-root
    rule reaches it - its owner is on the package's export chain - and before
    this wave it stamped ``export_root`` on it, which reads as "live because
    exported" where the truth is "live because called".
    """

    family = dead_code_family(
        tmp_path,
        _CALLED_AND_EXPORTED_TREE,
        "called-and-exported",
        scope_id=_SCOPE_ID,
    )
    reasons = live_root_reason_by_qualname(family)

    # Reachability of the guard: the export-root rule DID run on this tree and
    # did root the member nothing else holds live. A pin that only asserted an
    # absence would also pass on a tree the rule never reached.
    assert reasons.get("pkg.api:Service.render") == "export_root"
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


_API_MODULE = "distillations.api"
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
    in ``referenced_names`` - never as a qualname, which is exactly why the
    export-root owner's old qualname-only exclusion could not see it.
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


def _export_root_evidence() -> tuple[tuple[str, str], ...]:
    module_deps, candidates, referenced_qualnames, referenced_names = _liveness_inputs()
    registry = build_test_module_registry(
        root=Path(__file__).parent / "fixtures" / "liveness_policy"
    )
    already_live = entrypoints_mod.already_live_candidate_qualnames(
        dead_candidates=candidates,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
    )
    return entrypoints_mod.collect_project_export_root_evidence(
        module_deps=module_deps,
        referenced_qualnames=referenced_qualnames,
        dead_candidates=candidates,
        module_registry=registry,
        already_live_qualnames=already_live,
    )


def test_export_root_evidence_skips_what_an_internal_call_already_holds_live() -> None:
    """Direction A, the causal claim: no export root for a called member."""

    _, candidates, referenced_qualnames, referenced_names = _liveness_inputs()
    already_live = entrypoints_mod.already_live_candidate_qualnames(
        dead_candidates=candidates,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
    )

    # The population the guard compares, asserted rather than assumed: a guard
    # whose comparison set never contains the member cannot fire, and would
    # pass this pin in silence.
    assert f"{_API_MODULE}:Service.refresh" in already_live
    assert f"{_API_MODULE}:Service.render" not in already_live

    evidence = _export_root_evidence()

    assert (f"{_API_MODULE}:Service.render", "export_root") in evidence
    assert f"{_API_MODULE}:Service.refresh" not in dict(evidence)


def test_a_called_member_stays_live_when_the_export_root_evidence_is_removed() -> None:
    """Direction A, the causal independence: the call site carries it alone."""

    _, candidates, referenced_qualnames, referenced_names = _liveness_inputs()

    without_evidence = classify_liveness(
        definitions=candidates,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
    )

    dead = {item.qualname for item in without_evidence.dead_items}
    assert f"{_API_MODULE}:Service.refresh" not in dead
    # The same run must still be able to call something dead, or "not in dead"
    # is a statement about an empty set.
    assert f"{_API_MODULE}:Service.render" in dead


def test_an_uncalled_exported_member_depends_on_the_export_root_evidence() -> None:
    """Direction B: remove the export root and the verdict actually moves."""

    _, candidates, referenced_qualnames, referenced_names = _liveness_inputs()
    evidence = _export_root_evidence()
    rooted = frozenset(qualname for qualname, _reason in evidence)
    assert f"{_API_MODULE}:Service.render" in rooted

    with_evidence = classify_liveness(
        definitions=candidates,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames | rooted,
    )

    dead = {item.qualname for item in with_evidence.dead_items}
    assert f"{_API_MODULE}:Service.render" not in dead


def _opaque_base_class_metrics(qualname: str) -> ClassMetrics:
    return ClassMetrics(
        qualname=qualname,
        filepath=f"{qualname.partition(':')[0].replace('.', '/')}.py",
        start_line=1,
        end_line=9,
        cbo=0,
        lcom4=1,
        method_count=2,
        instance_var_count=0,
        risk_coupling="low",
        risk_cohesion="low",
        base_names=("external.Base",),
        has_unresolved_external_base=True,
    )


def test_an_abstained_member_is_not_already_live_and_keeps_its_export_root() -> None:
    """The carve-out, pinned: an abstention is neither dead nor live.

    A method whose owner inherits a base outside the analysis root abstains
    rather than being called dead, and an abstention is not a symbol something
    already holds live. Folding abstentions into "already live" would silently
    retire a root that is still the only export evidence there is - and would
    move the symbol from live into ``unresolved_external_override``, which is a
    different answer to the user, not a tidier one.
    """

    module_deps, candidates, referenced_qualnames, referenced_names = _liveness_inputs()
    class_metrics = (_opaque_base_class_metrics(f"{_API_MODULE}:Service"),)
    already_live = entrypoints_mod.already_live_candidate_qualnames(
        dead_candidates=candidates,
        referenced_names=referenced_names,
        referenced_qualnames=referenced_qualnames,
        class_metrics=class_metrics,
    )

    # The population really does abstain here, or the pin below is vacuous.
    abstained = {
        item.qualname
        for item in classify_liveness(
            definitions=candidates,
            referenced_names=referenced_names,
            referenced_qualnames=referenced_qualnames,
            class_metrics=class_metrics,
        ).unresolved_overrides
    }
    assert f"{_API_MODULE}:Service.render" in abstained
    assert f"{_API_MODULE}:Service.render" not in already_live

    registry = build_test_module_registry(
        root=Path(__file__).parent / "fixtures" / "liveness_policy"
    )
    evidence = entrypoints_mod.collect_project_export_root_evidence(
        module_deps=module_deps,
        referenced_qualnames=referenced_qualnames,
        dead_candidates=candidates,
        module_registry=registry,
        already_live_qualnames=already_live,
    )

    assert (f"{_API_MODULE}:Service.render", "export_root") in evidence
