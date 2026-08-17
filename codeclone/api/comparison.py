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
#: a different scope or interpreter is not "partly stale": nothing in it is
#: comparable, and degrading it per lane would report a trusted baseline for a run
#: the artifact does not describe.
CONTEXT_INCOMPATIBLE_REASONS = frozenset({"baseline_scope_id", "python_tag"})


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
    """The interpreter tag a baseline is judged against."""

    return current_python_tag()


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
    return ComparisonContext(
        new_func=new_func,
        new_block=new_block,
        metrics_diff=metrics_diff,
        coverage_adoption_diff_available=bool(
            metrics_trusted_for_diff and has_adoption
        ),
        api_surface_diff_available=bool(
            metrics_trusted_for_diff and api_snapshot is not None
        ),
    )


__all__ = [
    "CLONE_BLOCK_LANE",
    "CLONE_FUNCTION_LANE",
    "CONTEXT_INCOMPATIBLE_REASONS",
    "ComparisonContext",
    "blocking_lanes",
    "build_comparison_context",
    "lane_is_trusted",
    "lane_opacity_warning",
    "required_gate_lanes",
    "resolve_baseline_trust",
    "runtime_python_tag",
]
