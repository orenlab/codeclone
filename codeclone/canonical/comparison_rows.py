# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical epoch E2 (2026-09-26): the comparison tier's first families.

Every row here is a statement of ONE run compared against ONE baseline, and
every row says which baseline: ``baseline_scope_id`` and ``root_digest`` are
the container identity as the baseline package names it (the document's
``baseline.baseline_scope_id`` / ``baseline.root_digest_or_null``, the
container's ``meta.root_digest``).  Both are ``None`` exactly when the run had
no container to compare against — and that is still a comparison statement:
the witness says ``missing`` and every lane says why it cannot be compared.

The families bind to the seven closed productions of the ratified grammar
(``codeclone.canonical.grammar.SEMANTIC_KIND_TIERS``) and to nothing new:

* the baseline witnesses — clone and metrics — are ``baseline_witness``;
* per-lane trust is ``lane_trust``;
* per-lane availability is ``comparison_availability`` with THREE words
  (``compared`` / ``not_compared`` / ``unavailable``), and the fourth state is
  the ``disabled_capability`` production — a lane the run's observation
  contract did not enable carries no availability row at all.  Availability
  is not disabled, and the model proves the four states partition the lanes;
* the novelty of a finding is a ``novelty_annotation`` of the analysis family
  that carries the finding, one family per subject (the grammar admits ONE
  subject per annotation), keyed by the published finding id;
* the adoption and API deltas are ``delta_annotation`` of ``adoption_counts``
  and ``api_symbols`` — named delta rows of one shared shape, so the house
  couples to one delta type, not one per comparison.

What the field sets are is not chosen here: they are the fields the report
document's own comparison identity tier seals
(``report.document.integrity._comparison_digest_input`` and
``_COMPARISON_BASELINE_FIELDS`` / ``_COMPARISON_METRICS_BASELINE_FIELDS``) and
the keys ``contracts.report_identity`` classifies ``KEY_CLASS_COMPARISON``.
The baseline's own ``python_tag`` rides the witness as artifact provenance —
the container's root digest already binds it, so it adds no identity the
digest does not carry; the RUNTIME tag does not ride anything: it is the
interpreter of this execution, and a store run keyed by it would split one
report identity into two store runs (the DET-01 class).

Two populations are deliberately NOT stored, and the reason is the three-class
law, not omission: the novelty of an UNGOVERNED finding (structural,
unreachable statements, cohesion, coverage, segment clones, authority) is a
constant of its family — no baseline lane carries its identity — and the
health delta is an evaluation-domain fact (the report identity registry
digests ``metrics.families.health`` whole in the evaluation tier), whose
subject family arrives with the evaluation tier.

Nothing in this module reaches the wire: until the wire-revision bump the
comparison house is internal model and store state (ruling 2026-09-26).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from codeclone.canonical.errors import CanonicalModelError
from codeclone.findings.ids import clone_group_id, dead_code_group_id, design_group_id

#: ``baseline.state`` of the document: no container, every lane of an
#: authenticated container trusted, or anything less.
BASELINE_WITNESS_MISSING: Final = "missing"
BASELINE_WITNESS_STATES: Final = ("missing", "trusted", "untrusted")

#: The clone-baseline status vocabulary (``codeclone.baseline.BaselineStatus``),
#: mirrored verbatim and pinned against the enum by test.
BASELINE_STATUSES: Final = (
    "generator_mismatch",
    "integrity_failed",
    "integrity_missing",
    "invalid_json",
    "invalid_type",
    "mismatch_fingerprint_version",
    "mismatch_python_version",
    "mismatch_schema_version",
    "mismatch_scope_id",
    "missing",
    "missing_fields",
    "ok",
    "too_large",
)

#: The metrics-baseline status vocabulary
#: (``codeclone.baseline.MetricsBaselineStatus``), mirrored and pinned the same
#: way.
METRICS_BASELINE_STATUSES: Final = (
    "generator_mismatch",
    "incompatible_metrics_contract",
    "integrity_failed",
    "integrity_missing",
    "invalid_json",
    "invalid_type",
    "mismatch_python_version",
    "mismatch_schema_version",
    "mismatch_scope_id",
    "missing",
    "missing_fields",
    "ok",
    "too_large",
)

#: The status a loaded baseline carries, on both witnesses.
BASELINE_STATUS_OK: Final = "ok"

#: The observation lanes (``codeclone.models.ObservationLaneName``), mirrored
#: and pinned against the literal by test.
OBSERVATION_LANES: Final = (
    "adoption_counts",
    "api_surface",
    "clones.blocks",
    "clones.functions",
    "coupling_cohesion_observations",
    "dead_code",
    "dependencies",
    "module_identity",
    "risk_observations",
    "semantic_authority",
)

#: The lanes a baseline comparison has a term for.  ``module_identity`` and
#: ``semantic_authority`` carry none (the authority lane's novelty is the
#: document's constant ``semantic_authority_comparison_unavailable``), so they
#: have no availability to state.
COMPARED_LANES: Final = (
    "adoption_counts",
    "api_surface",
    "clones.blocks",
    "clones.functions",
    "coupling_cohesion_observations",
    "dead_code",
    "dependencies",
    "risk_observations",
)

#: The report document's metrics family whose ``summary.baseline_diff_available``
#: states whether each METRIC lane's comparison ran — the pairing
#: ``core.reporting._metrics_for_report`` writes (pinned against its source by
#: test).  The two clone lanes are not here: the document states their
#: comparison per group, through ``novelty_reason``.
COMPARISON_LANE_FAMILIES: Final[dict[str, str]] = {
    "adoption_counts": "coverage_adoption",
    "api_surface": "api_surface",
    "coupling_cohesion_observations": "coupling",
    "dead_code": "dead_code",
    "dependencies": "dependencies",
    "risk_observations": "complexity",
}
#: The clone lane of each emitted clone kind the baseline compares.
CLONE_KIND_LANES: Final[dict[str, str]] = {
    "block": "clones.blocks",
    "function": "clones.functions",
}
#: The ``novelty_reason`` of a clone group whose lane was comparable and not
#: compared in this run (``report.document._common``).
NOVELTY_REASON_COMPARISON_UNAVAILABLE: Final = "comparison_unavailable"

#: Per-lane trust as the document publishes it (``baseline.sorted_lane_trust``).
LANE_TRUSTED: Final = "trusted"
LANE_TRUST_STATUSES: Final = ("trusted", "unavailable")
#: The reason a trusted lane carries, and the reason every lane carries when
#: there is no container at all.
LANE_TRUST_COMPATIBLE: Final = "compatible"
LANE_TRUST_BASELINE_MISSING: Final = "baseline_missing"
#: ``codeclone.models.LaneTrustReason`` plus the two reasons the document adds
#: for a lane the trust vector cannot vouch for (no container / unverified
#: root), pinned against the literal by test.
LANE_TRUST_REASONS: Final = (
    "algorithm_revision",
    "baseline_missing",
    "baseline_scope_id",
    "canonicalization_version",
    "compatible",
    "descriptor_version",
    "lane_digest_mismatch",
    "payload_schema",
    "payload_schema_outdated",
    "required_contract",
    "root_digest_mismatch",
    "root_unverified",
    "runtime_lane_unknown",
)

#: The three availability words; ``disabled`` is NOT one of them — it is the
#: ``disabled_capability`` production, a different fact about the run.
AVAILABILITY_COMPARED: Final = "compared"
AVAILABILITY_NOT_COMPARED: Final = "not_compared"
AVAILABILITY_UNAVAILABLE: Final = "unavailable"
COMPARISON_AVAILABILITY_STATES: Final = (
    AVAILABILITY_COMPARED,
    AVAILABILITY_NOT_COMPARED,
    AVAILABILITY_UNAVAILABLE,
)

#: The tri-state novelty word (``codeclone.domain.findings.CLONE_NOVELTY_*``).
NOVELTY_NEW: Final = "new"
NOVELTY_KNOWN: Final = "known"
NOVELTY_UNAVAILABLE: Final = "unavailable"
NOVELTY_WORDS: Final = (NOVELTY_KNOWN, NOVELTY_NEW, NOVELTY_UNAVAILABLE)
#: The reasons a GOVERNED finding may be ``unavailable`` for
#: (``report.document._common``): its lane is not comparable, its lane was
#: comparable and not compared, or the comparison ran and the entity was
#: outside its population.  ``not_baseline_governed`` is the ungoverned
#: families' constant and never reaches a stored row.
GOVERNED_NOVELTY_REASONS: Final = (
    "comparison_unavailable",
    "entity_not_compared",
    "lane_unavailable",
)

#: The finding-id prefixes of every novelty family, spelled through the ONE
#: id owner (``codeclone.findings.ids``): a row filed under the wrong subject
#: family is refused, never silently counted.
NOVELTY_FAMILY_ID_PREFIXES: Final[dict[str, tuple[str, ...]]] = {
    "clone_novelty": (clone_group_id("block", ""), clone_group_id("function", "")),
    "complexity_novelty": (design_group_id("complexity", ""),),
    "coupling_novelty": (design_group_id("coupling", ""),),
    "dead_symbol_novelty": (dead_code_group_id(""),),
    "dependency_cycle_novelty": (design_group_id("dependency", ""),),
}

#: The clone lane each clone-novelty id prefix belongs to.
CLONE_NOVELTY_LANES: Final[dict[str, str]] = {
    clone_group_id("block", ""): "clones.blocks",
    clone_group_id("function", ""): "clones.functions",
}


def comparison_availability_state(*, compared: bool, lane_trusted: bool) -> str:
    """The one owner of the availability word, read by the ingest oracle and
    the producer-native snapshot alike.

    A comparison that ran is ``compared`` — its result, zero included, is a
    measurement.  One that did not run is ``not_compared`` when the lane could
    have been compared and ``unavailable`` when it could not: two absences,
    two words, never folded into one.
    """
    if compared:
        return AVAILABILITY_COMPARED
    if lane_trusted:
        return AVAILABILITY_NOT_COMPARED
    return AVAILABILITY_UNAVAILABLE


def baseline_statuses_stated(meta: Mapping[str, object]) -> bool:
    """Whether a meta block states a status for BOTH baselines — the
    precondition of a comparison witness, read by the producer-native
    snapshot and the ingest oracle alike.  A meta that states neither (a
    caller that handed ``report`` an empty meta) witnessed no comparison."""
    for key in ("baseline", "metrics_baseline"):
        block = meta.get(key)
        if not isinstance(block, Mapping) or not isinstance(block.get("status"), str):
            return False
    return True


def _require_member(value: object, vocabulary: tuple[str, ...], what: str) -> None:
    if not isinstance(value, str) or value not in vocabulary:
        raise CanonicalModelError(f"unknown {what}: {value!r}")


def _require_text(value: object, what: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise CanonicalModelError(f"{what} must be a non-empty string: {value!r}")


def _require_optional_text(value: object, what: str) -> None:
    if value is not None:
        _require_text(value, what)


def _require_flag(value: object, what: str) -> None:
    if not isinstance(value, bool):
        raise CanonicalModelError(f"{what} must be a bool: {value!r}")


def _require_int(value: object, what: str, *, floor: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise CanonicalModelError(f"{what} must be an int: {value!r}")
    if floor is not None and value < floor:
        raise CanonicalModelError(f"{what} must be at least {floor}: {value!r}")


class _Compared(Protocol):
    """Every comparison row: the baseline it was compared against."""

    @property
    def baseline_scope_id(self) -> str | None: ...

    @property
    def root_digest(self) -> str | None: ...


def baseline_identity(row: _Compared) -> tuple[str | None, str | None]:
    """The container identity one comparison row states."""
    return (row.baseline_scope_id, row.root_digest)


def _require_identity(row: _Compared, what: str) -> None:
    """Both halves or neither: a scope without a digest names no container."""
    scope_id, root_digest = baseline_identity(row)
    if (scope_id is None) != (root_digest is None):
        raise CanonicalModelError(
            f"{what} carries half a baseline identity "
            f"(scope {scope_id!r}, root digest {root_digest!r})"
        )
    _require_optional_text(scope_id, f"{what} baseline scope id")
    _require_optional_text(root_digest, f"{what} root digest")


def _require_compared_identity(row: _Compared, what: str) -> None:
    """A result of a comparison names the baseline it was compared against."""
    _require_identity(row, what)
    if row.baseline_scope_id is None:
        raise CanonicalModelError(
            f"{what} states a comparison result against no baseline"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BaselineWitnessRecord:
    """Cmp1: the clone baseline this run was compared against, ONE per run.

    ``state``/identity are the document's comparison section; ``loaded``,
    ``status``, ``fingerprint_version``, ``schema_version`` and
    ``payload_sha256`` its ``meta.baseline`` comparison fields; ``python_tag``
    the artifact's provenance.  ``payload_sha256_verified`` is not stored:
    it is ``loaded and status == ok and payload_sha256 is not None`` by its one
    owner (``report.meta``).  The surfaces' ``trusted`` is not stored either:
    both baseline resolvers set ``trusted_for_diff`` exactly when they set
    ``loaded``, and the MCP shadow pin holds that on both populations.
    """

    baseline_scope_id: str | None
    root_digest: str | None
    state: str
    loaded: bool
    status: str
    fingerprint_version: str | None
    schema_version: str | None
    python_tag: str | None
    payload_sha256: str | None

    def __post_init__(self) -> None:
        what = "baseline witness"
        _require_identity(self, what)
        _require_member(self.state, BASELINE_WITNESS_STATES, f"{what} state")
        _require_flag(self.loaded, f"{what} loaded")
        _require_member(self.status, BASELINE_STATUSES, f"{what} status")
        for name in (
            "fingerprint_version",
            "schema_version",
            "python_tag",
            "payload_sha256",
        ):
            _require_optional_text(getattr(self, name), f"{what} {name}")
        missing = self.state == BASELINE_WITNESS_MISSING
        if missing != (self.baseline_scope_id is None):
            raise CanonicalModelError(
                f"{what} state {self.state!r} contradicts its container "
                f"identity {baseline_identity(self)!r}: ``missing`` is exactly "
                "the run without a container"
            )
        if self.loaded and self.status != BASELINE_STATUS_OK:
            raise CanonicalModelError(
                f"{what} is loaded under the failure status {self.status!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class MetricsBaselineWitnessRecord:
    """Cmp2: the metrics baseline this run was compared against, ONE per run.

    The metrics lanes ride the same container as the clone lanes, so its
    identity is the run's one container identity; the fields are the
    document's ``meta.metrics_baseline`` comparison fields.
    """

    baseline_scope_id: str | None
    root_digest: str | None
    loaded: bool
    status: str
    schema_version: str | None
    payload_sha256: str | None

    def __post_init__(self) -> None:
        what = "metrics baseline witness"
        _require_identity(self, what)
        _require_flag(self.loaded, f"{what} loaded")
        _require_member(self.status, METRICS_BASELINE_STATUSES, f"{what} status")
        _require_optional_text(self.schema_version, f"{what} schema_version")
        _require_optional_text(self.payload_sha256, f"{what} payload_sha256")
        if self.loaded and self.status != BASELINE_STATUS_OK:
            raise CanonicalModelError(
                f"{what} is loaded under the failure status {self.status!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class LaneTrustRow:
    """Cmp3: whether one lane of the container is comparable for this run.

    Keyed by ``lane``.  A lane is ``trusted`` exactly when its reason is
    ``compatible``, and ``baseline_missing`` is exactly the reason of a run
    without a container.
    """

    baseline_scope_id: str | None
    root_digest: str | None
    lane: str
    status: str
    reason: str

    def __post_init__(self) -> None:
        what = "lane trust"
        _require_identity(self, what)
        _require_member(self.lane, OBSERVATION_LANES, f"{what} lane")
        _require_member(self.status, LANE_TRUST_STATUSES, f"{what} status")
        _require_member(self.reason, LANE_TRUST_REASONS, f"{what} reason")
        if (self.status == LANE_TRUSTED) != (self.reason == LANE_TRUST_COMPATIBLE):
            raise CanonicalModelError(
                f"{what} of {self.lane!r}: status {self.status!r} contradicts "
                f"reason {self.reason!r}"
            )
        if (self.reason == LANE_TRUST_BASELINE_MISSING) != (
            self.baseline_scope_id is None
        ):
            raise CanonicalModelError(
                f"{what} of {self.lane!r}: reason {self.reason!r} contradicts "
                f"the container identity {baseline_identity(self)!r}"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class DisabledCapabilityRow:
    """The fourth availability state: a lane this run's observation contract
    did not enable.  Keyed by ``lane``; never also an availability row."""

    baseline_scope_id: str | None
    root_digest: str | None
    lane: str

    def __post_init__(self) -> None:
        _require_identity(self, "disabled capability")
        _require_member(self.lane, OBSERVATION_LANES, "disabled capability lane")


@dataclass(frozen=True, slots=True, kw_only=True)
class ComparisonAvailabilityRow:
    """Cmp7: whether the comparison of one enabled lane ran, and if not, which
    absence it is.  Keyed by ``lane``; only the lanes a comparison has a term
    for carry one."""

    baseline_scope_id: str | None
    root_digest: str | None
    lane: str
    availability: str

    def __post_init__(self) -> None:
        what = "comparison availability"
        _require_identity(self, what)
        _require_member(self.lane, COMPARED_LANES, f"{what} lane")
        _require_member(
            self.availability, COMPARISON_AVAILABILITY_STATES, f"{what} word"
        )
        if (
            self.baseline_scope_id is None
            and self.availability != AVAILABILITY_UNAVAILABLE
        ):
            raise CanonicalModelError(
                f"{what} of {self.lane!r} is {self.availability!r} without a "
                "container: nothing could be compared"
            )


@dataclass(frozen=True, slots=True, kw_only=True)
class FindingNoveltyRow:
    """Cmp4: the novelty of one published finding of a governed family.

    Keyed by the published finding id — the handle the finding's own family
    projects through ``codeclone.findings.ids`` — so the annotation references
    its subject and never embeds it.  ``new`` and ``known`` are verdicts of a
    comparison and carry no reason; ``unavailable`` always says which absence
    it is.
    """

    baseline_scope_id: str | None
    root_digest: str | None
    finding_id: str
    novelty: str
    novelty_reason: str | None

    def __post_init__(self) -> None:
        what = f"novelty of {self.finding_id!r}"
        _require_identity(self, what)
        _require_text(self.finding_id, "novelty finding id")
        _require_member(self.novelty, NOVELTY_WORDS, f"{what} word")
        if self.novelty == NOVELTY_UNAVAILABLE:
            _require_member(
                self.novelty_reason, GOVERNED_NOVELTY_REASONS, f"{what} reason"
            )
            return
        if self.novelty_reason is not None:
            raise CanonicalModelError(
                f"{what} is a verdict ({self.novelty!r}) and carries a reason "
                f"({self.novelty_reason!r})"
            )
        if self.baseline_scope_id is None:
            raise CanonicalModelError(f"{what} is {self.novelty!r} against no baseline")


#: The delta terms each delta family states — all of them when its
#: comparison ran, none when it did not.  The names are the producer's
#: (``MetricsDiff`` and the surfaces' ``diff`` block).
DELTA_FAMILY_TERMS: Final[dict[str, tuple[str, ...]]] = {
    "adoption_delta": (
        "docstring_permille_delta",
        "typing_param_permille_delta",
        "typing_return_permille_delta",
    ),
    "api_surface_delta": (
        "api_breaking_changes",
        "api_signature_changes",
        "new_api_symbols",
    ),
}
#: The terms that are counts of a comparison's findings, never negative; a
#: permille delta may be.
COUNT_DELTA_TERMS: Final = frozenset(DELTA_FAMILY_TERMS["api_surface_delta"])
_DELTA_TERMS: Final = frozenset(
    term for terms in DELTA_FAMILY_TERMS.values() for term in terms
)


@dataclass(frozen=True, slots=True, kw_only=True)
class MetricDeltaRow:
    """Cmp5: one named delta of one metric comparison.

    The adoption comparison states three permille deltas (``adoption_delta``,
    a delta annotation of ``adoption_counts``), the API comparison three
    counts (``api_surface_delta``, of ``api_symbols``); both families share
    this one row shape and are keyed by ``delta``.  The model admits a family
    whole or not at all, and exactly when its comparison ran.
    ``api_signature_changes`` (compatible) is counted beside
    ``api_breaking_changes`` and never inside it.
    """

    baseline_scope_id: str | None
    root_digest: str | None
    delta: str
    value: int

    def __post_init__(self) -> None:
        what = f"delta {self.delta!r}"
        _require_compared_identity(self, what)
        if self.delta not in _DELTA_TERMS:
            raise CanonicalModelError(f"unknown delta term: {self.delta!r}")
        _require_int(
            self.value,
            f"{what} value",
            floor=0 if self.delta in COUNT_DELTA_TERMS else None,
        )


__all__ = [
    "AVAILABILITY_COMPARED",
    "AVAILABILITY_NOT_COMPARED",
    "AVAILABILITY_UNAVAILABLE",
    "BASELINE_STATUSES",
    "BASELINE_STATUS_OK",
    "BASELINE_WITNESS_MISSING",
    "BASELINE_WITNESS_STATES",
    "CLONE_KIND_LANES",
    "CLONE_NOVELTY_LANES",
    "COMPARED_LANES",
    "COMPARISON_AVAILABILITY_STATES",
    "COMPARISON_LANE_FAMILIES",
    "COUNT_DELTA_TERMS",
    "DELTA_FAMILY_TERMS",
    "GOVERNED_NOVELTY_REASONS",
    "LANE_TRUSTED",
    "LANE_TRUST_BASELINE_MISSING",
    "LANE_TRUST_COMPATIBLE",
    "LANE_TRUST_REASONS",
    "LANE_TRUST_STATUSES",
    "METRICS_BASELINE_STATUSES",
    "NOVELTY_FAMILY_ID_PREFIXES",
    "NOVELTY_KNOWN",
    "NOVELTY_NEW",
    "NOVELTY_REASON_COMPARISON_UNAVAILABLE",
    "NOVELTY_UNAVAILABLE",
    "NOVELTY_WORDS",
    "OBSERVATION_LANES",
    "BaselineWitnessRecord",
    "ComparisonAvailabilityRow",
    "DisabledCapabilityRow",
    "FindingNoveltyRow",
    "LaneTrustRow",
    "MetricDeltaRow",
    "MetricsBaselineWitnessRecord",
    "baseline_identity",
    "baseline_statuses_stated",
    "comparison_availability_state",
]
