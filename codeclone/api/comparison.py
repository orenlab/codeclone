# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Minimal R3 door for "was this family compared, and what came out of it".

Comparison availability is a published fact, never an inference (`B8`). Before
this door the CLI and MCP each decided it for themselves: the CLI asked the
container per lane, MCP asked the all-or-nothing ``verify_compatibility``. One
degraded non-clone lane was therefore enough to make the two surfaces publish
opposite answers about the same clone in the same repository state -- MCP said
``known`` where the CLI said ``new``, with no comparison executed on either side
of that word, and six metric families lost a comparison the CLI kept. Two trust
authorities over one artifact is the defect class itself (`G3`), so the decision
lives here once and both surfaces consume it.

It lives at R3 because that is the only ring both surfaces may reach: R4 imports
R0/R1/R3/R4, and the architecture ratchet is shrink-only. The ratchet was
reporting a wrong design rather than asking for an exception.

The absent case is representable: ``new_func``/``new_block`` are ``None`` when
that lane was not compared, and an empty frozenset only when a comparison ran
and found nothing (`RP2`, `G4`). An empty difference set with no comparison is
not evidence of sameness.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..baseline.trust import current_python_tag
from ..contracts import population_universe_observed
from ..core.reporting import gate_required_lanes, resolve_report_baseline_trust

if TYPE_CHECKING:
    from ..baseline import Baseline, MetricsBaseline
    from ..models import (
        BaselineContainerV3,
        GroupMapLike,
        LaneTrust,
        MetricsDiff,
        ProjectMetrics,
        TrustVector,
    )

#: The two clone lanes the baseline container carries a comparison term for.
CLONE_FUNCTION_LANE = "clones.functions"
CLONE_BLOCK_LANE = "clones.blocks"

#: Lane-trust reasons that are not lane facts at all. Comparison-*context*
#: compatibility asks whether this artifact applies to this run, and there is one
#: answer for the whole container (`B4`). ``unavailable_lanes`` reports it as a
#: row per lane because that is the shape it returns, but a container belonging to
#: a different scope is not "partly stale": nothing in it is comparable, and
#: degrading it per lane would report a trusted baseline for a run the artifact
#: does not describe.
#:
#: This set once also held ``python_tag``, and that half was wrong. Scope is a
#: statement about *which input universe* the artifact describes; the interpreter
#: tag is a statement about *where the artifact was taken*, and the measurement
#: (CPython 3.10-3.14: all ten lane payloads byte-identical, zero observational
#: fields differing) shows the second changes nothing this door decides. Rejecting
#: on it condemned every lane of an authentic container over a property the lanes
#: do not carry. The tag survives as provenance, reported by
#: ``foreign_interpreter_provenance`` below, and no longer as a verdict.
CONTEXT_INCOMPATIBLE_REASONS = frozenset({"baseline_scope_id"})


@dataclass(frozen=True, kw_only=True, slots=True)
class ComparisonContext:
    """What the baseline comparison produced for this run, per family.

    ``None`` means "this lane was not compared"; a frozenset means "compared",
    and an empty one means "compared, nothing new". A consumer MUST NOT read an
    empty set as proof of sameness -- that is what the ``None`` is for.
    """

    new_func: frozenset[str] | None
    new_block: frozenset[str] | None
    metrics_diff: MetricsDiff | None
    coverage_adoption_diff_available: bool
    api_surface_diff_available: bool

    @property
    def clone_novelty_available(self) -> bool:
        """True when at least one clone lane was actually compared."""

        return self.new_func is not None or self.new_block is not None

    @property
    def new_clones_count(self) -> int:
        """New clone groups across the lanes that were compared.

        A lane that was not compared contributes nothing rather than zero; the
        caller learns which case it is from ``clone_novelty_available``, never
        from this number.
        """

        return len(self.new_func or ()) + len(self.new_block or ())


def lane_is_trusted(trust: TrustVector | None, lane: str) -> bool:
    """Per-lane compatibility for one lane of a root-authenticated container.

    Root authenticity gates every lane: an unverified root makes each lane's own
    digest meaningless, so no lane is comparable through it (`B6`).
    """

    return bool(
        trust is not None
        and trust.root_verified
        and any(item.name == lane and item.status == "trusted" for item in trust.lanes)
    )


def required_gate_lanes(
    *, args: object, enabled_lanes: Collection[str]
) -> frozenset[str]:
    """Lanes the currently active gates read, from the sole owner of gate policy.

    A surface never re-derives which gate reads which lane; it receives plain
    lane names and only ever intersects them.
    """

    return gate_required_lanes(args=args, enabled_lanes=enabled_lanes)


def resolve_baseline_trust(
    container: BaselineContainerV3 | None,
    *,
    baseline_scope_id: str | None,
) -> TrustVector | None:
    """The per-lane trust vector for one container, from its sole owner."""

    return resolve_report_baseline_trust(
        container,
        baseline_scope_id=baseline_scope_id,
    )


def blocking_lanes(
    unavailable: Sequence[LaneTrust],
    *,
    required_lanes: frozenset[str],
) -> tuple[str, ...]:
    """Opaque lanes that must keep this run fail-closed.

    Two different questions, kept apart. Context incompatibility condemns the
    container whatever the gates read. Per-lane staleness condemns only the lanes
    an active gate actually reads, so a lane nobody gates on is reported opaque
    and MUST NOT condemn the container (`B5`).
    """

    context = {
        item.name for item in unavailable if item.reason in CONTEXT_INCOMPATIBLE_REASONS
    }
    if context:
        return tuple(sorted(context))
    return tuple(sorted({item.name for item in unavailable} & required_lanes))


def lane_opacity_warning(unavailable: Sequence[LaneTrust]) -> str:
    """Name the opaque lanes, so degrading never reads as ignoring (`RP2`)."""

    reasons = ", ".join(f"{item.name}:{item.reason}" for item in unavailable)
    return (
        f"Baseline lanes are opaque for this run: {reasons}. No active gate reads "
        "them, so the run continues. Their baseline-relative novelty is reported "
        "as unavailable, not as zero."
    )


def runtime_python_tag() -> str:
    """The interpreter tag a baseline is stamped with when it is published."""

    return current_python_tag()


def foreign_interpreter_provenance(
    *,
    baseline_python_tag: str | None,
    runtime_python_tag: str,
) -> str | None:
    """The interpreter a usable baseline was taken on, when it was not this one.

    A remark about origin, never a verdict about trust. The tag stopped gating
    comparability because it is measured not to change any lane payload across
    CPython 3.10-3.14, but it remains a true and useful fact about the artifact:
    the operator is entitled to know that the reference they are being compared
    against was produced somewhere else, and staying silent about a fact we hold
    would trade one `G4` failure for another.

    ``None`` means there is no remark to make -- either no tag is known (no
    baseline was loaded, or it carried none) or the baseline was taken on this
    very interpreter. Both are the absence of a *difference*, which is the only
    thing this function reports; whether a baseline loaded at all is a separate
    fact its caller already holds and must not re-derive from this one (`G2`).

    Computed here, in the one ring both the CLI and MCP may reach, so the two
    surfaces cannot drift into two answers about one artifact (`G3`). Callers
    render it; they do not recompute it (`P3`, `G1`).
    """

    if not baseline_python_tag:
        return None
    if baseline_python_tag == runtime_python_tag:
        return None
    return baseline_python_tag


def build_comparison_context(
    *,
    func_groups: GroupMapLike,
    block_groups: GroupMapLike,
    project_metrics: ProjectMetrics | None,
    clone_baseline: Baseline,
    clone_trusted_for_diff: bool,
    metrics_baseline: MetricsBaseline,
    metrics_trusted_for_diff: bool,
    baseline_trust: TrustVector | None,
) -> ComparisonContext:
    """Run the comparisons this run is entitled to, and report which ran.

    Per-lane compatibility decides the clone lanes: a degraded ``api_surface``
    lane leaves the clone comparison intact, and an opaque ``clones.*`` lane
    leaves that lane -- and only that lane -- uncompared (`B5`).
    ``clone_trusted_for_diff`` is the fallback for runs with no trust vector at
    all (no container, or no scope id to evaluate one against), where nothing
    per-lane can be said.
    """

    function_lane_trusted = (
        clone_trusted_for_diff
        if baseline_trust is None
        else lane_is_trusted(baseline_trust, CLONE_FUNCTION_LANE)
    )
    block_lane_trusted = (
        clone_trusted_for_diff
        if baseline_trust is None
        else lane_is_trusted(baseline_trust, CLONE_BLOCK_LANE)
    )
    new_func: frozenset[str] | None = None
    new_block: frozenset[str] | None = None
    if function_lane_trusted or block_lane_trusted:
        diff_func, diff_block = clone_baseline.diff(func_groups, block_groups)
        if function_lane_trusted:
            new_func = frozenset(diff_func)
        if block_lane_trusted:
            new_block = frozenset(diff_block)
    metrics_diff = None
    if project_metrics is not None and metrics_trusted_for_diff:
        metrics_diff = metrics_baseline.diff(project_metrics)
    # A trusted metrics baseline is necessary but not sufficient: a container
    # written before a lane existed carries no snapshot for it, and a comparison
    # with no baseline term did not run (`B8`).
    has_adoption = getattr(metrics_baseline, "has_coverage_adoption_snapshot", False)
    api_snapshot = getattr(metrics_baseline, "api_surface_snapshot", None)
    # The API comparison additionally needs the *current* term's universe
    # observed. It is a set-membership diff, and membership manufactures facts
    # from absence: the current surface is collected only from modules
    # actually read, so an unread module's symbols are indistinguishable from
    # removed ones — an ``unmeasured`` run fabricates the whole baseline API
    # as torn down, a ``partial`` run fabricates each unread module pointwise,
    # both beside ``baseline_diff_available: true`` (`B8`, `G4`). The
    # population fact has one owner in the contract ring; ``complete_empty``
    # stays available there because a genuinely emptied scope really did
    # remove what the baseline remembers, and that signal must survive.
    api_universe_observed = (
        project_metrics is not None
        and population_universe_observed(project_metrics.health.population)
    )
    return ComparisonContext(
        new_func=new_func,
        new_block=new_block,
        metrics_diff=metrics_diff,
        coverage_adoption_diff_available=bool(
            metrics_trusted_for_diff and has_adoption
        ),
        api_surface_diff_available=bool(
            metrics_trusted_for_diff
            and api_snapshot is not None
            and api_universe_observed
        ),
    )


__all__ = [
    "CLONE_BLOCK_LANE",
    "CLONE_FUNCTION_LANE",
    "CONTEXT_INCOMPATIBLE_REASONS",
    "ComparisonContext",
    "blocking_lanes",
    "build_comparison_context",
    "foreign_interpreter_provenance",
    "lane_is_trusted",
    "lane_opacity_warning",
    "required_gate_lanes",
    "resolve_baseline_trust",
    "runtime_python_tag",
]
