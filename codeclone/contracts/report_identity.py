# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""The producer/family registry of the report's semantic identity.

RULING-2026-08-31 (report identity v2) ratified one law and one ratchet:

    Two runs share a ``run_id`` iff they utter the same canonical set of
    semantic statements under the same realized contract of their
    derivation.

    Every canonical semantic family of the report has exactly one
    registered owner.

Before this table existed the answer to "what moves the run identity" was
re-written in four dialects (observation lane descriptors, the report digest
field lists, the canonical store's witness layers, the cache reuse profiles),
and the findings tiers had no owner at all: five measured
(tree x config x engine) states shared one ``run_id`` because near-miss
containers, policy parameters and evaluation outputs were outside every
preimage.  This module is the single owner for the report's semantic
families; the observation lanes keep their own descriptors (they were always
identity-bearing) and share only the revision constants.

Two deliberate boundaries, both from the ruling:

* **Realized beats registered.**  The registry names which constant owns a
  family's revision, but the identity hashes what the document actually
  utters: a container that prints its ``algorithm_revision`` is the realized
  truth, and verification never compares a document against this process's
  constants — an old document stays honestly interpretable in its own
  generation.  The live-constant lookup below exists for families whose
  containers do not utter their revision.
* **Disabled utters no contract.**  A producer whose only statement is
  ``state=disabled`` contributes that state to the analysis population and
  nothing else: its configured revision must not sneak into the identity
  through a global registry digest.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal

IdentityDomain = Literal["analysis", "evaluation"]
#: How a producer comes to run: ``always`` producers run in every analysis
#: that yields a document; ``lane`` producers run iff their observation lane
#: is enabled; ``opt_in`` producers run iff their flag was passed (their
#: containers self-witness through ``state``); ``metrics`` producers run iff
#: their family is in ``meta.computed_metric_families``.
ProducerActivation = Literal["always", "lane", "opt_in", "metrics"]

#: One registered owner of one canonical semantic family, as pure data —
#: the repo's table idiom (``_FAMILY_NAMESPACE``, ``_PAYLOAD_SCHEMAS``), and
#: deliberately not a dataclass: runtime model shapes belong to the model
#: store (the phase-39S boundary), while this is a constants table.
#:
#: Keys:
#: ``family``            canonical family name (one owner per family)
#: ``identity_domain``   "analysis" | "evaluation"
#: ``revision_owners``   ((semantic_name, contracts_constant_name), ...) —
#:                       resolved live against :mod:`codeclone.contracts` by
#:                       :func:`registered_revisions`
#: ``activation``        ProducerActivation
#: ``enabling_lane``     for activation == "lane": the observation lane whose
#:                       enablement witnesses execution (else None)
#: ``identity_keys``     container keys this producer GLUES entity identity
#:                       into (dedup keys, group ids, fingerprints).  The law
#:                       (controller mutation 2026-08-31, survived and closed):
#:                       an identity-bearing key may never be declared
#:                       non-semantic by the family-digest projection — a
#:                       location glued into an identity key is identity, not
#:                       provenance (the F1 precedent).
ProducerSpec = Mapping[str, object]

#: The closed producer-state vocabulary of the analysis population.
#: ``complete`` is the only state under which a family digest may exist:
#: ``count = 0`` is a completed measurement, absence of execution is never
#: projected into a zero.  The wider five-state model (``truncated``,
#: ``unavailable``, ``not_executed``) is owned by the canonical
#: AnalysisPopulation authority; the report side utters only the states its
#: documents can currently witness.
PRODUCER_STATE_COMPLETE: Final = "complete"
PRODUCER_STATE_DISABLED: Final = "disabled"


REPORT_SEMANTIC_PRODUCERS: Final[tuple[ProducerSpec, ...]] = (
    {
        "family": "authority",
        "identity_keys": ("id",),
        "identity_domain": "analysis",
        "revision_owners": (("authority_analysis", "AUTHORITY_ANALYSIS_REVISION"),),
        "activation": "lane",
        "enabling_lane": "semantic_authority",
    },
    {
        "family": "clones",
        "identity_keys": ("fingerprint", "group_key", "id"),
        "identity_domain": "analysis",
        "revision_owners": (("clone_fingerprint", "BASELINE_FINGERPRINT_VERSION"),),
        "activation": "always",
    },
    {
        "family": "dead_code",
        "identity_keys": ("id",),
        "identity_domain": "analysis",
        "revision_owners": (
            ("liveness", "LIVENESS_POLICY_VERSION"),
            ("statement_reachability", "STATEMENT_REACHABILITY_POLICY_VERSION"),
        ),
        "activation": "lane",
        "enabling_lane": "dead_code",
    },
    {
        "family": "design",
        "identity_keys": (),
        "identity_domain": "analysis",
        "revision_owners": (
            ("complexity_metrics", "COMPLEXITY_ALGORITHM_REVISION"),
            ("design_metrics", "DESIGN_METRICS_ALGORITHM_REVISION"),
        ),
        "activation": "lane",
        "enabling_lane": "risk_observations",
    },
    {
        "family": "gates",
        "identity_keys": (),
        "identity_domain": "evaluation",
        "revision_owners": (
            ("gate_algorithm", "GATE_ALGORITHM_REVISION"),
            ("gate_lane_matrix", "GATE_LANE_MATRIX_VERSION"),
            ("health_input_manifest", "HEALTH_INPUT_MANIFEST_VERSION"),
        ),
        "activation": "always",
    },
    {
        "family": "health",
        "identity_keys": (),
        "identity_domain": "evaluation",
        "revision_owners": (("health_algorithm", "HEALTH_ALGORITHM_REVISION"),),
        "activation": "metrics",
    },
    {
        "family": "near_miss",
        "identity_keys": ("pair_key",),
        "identity_domain": "analysis",
        "revision_owners": (("near_miss", "NEAR_MISS_ALGORITHM_REVISION"),),
        "activation": "opt_in",
    },
    {
        "family": "renamed_structure",
        "identity_keys": ("fingerprint", "group_key"),
        "identity_domain": "analysis",
        "revision_owners": (
            ("renamed_structure", "RENAMED_STRUCTURE_ALGORITHM_REVISION"),
        ),
        "activation": "opt_in",
    },
    {
        "family": "structural",
        "identity_keys": ("id",),
        "identity_domain": "analysis",
        "revision_owners": (
            ("structural_findings_catalog", "STRUCTURAL_FINDINGS_CATALOG_VERSION"),
        ),
        "activation": "always",
    },
)

#: The live evaluation parameters of the health formula, as
#: ``(semantic_name, contracts_constant_name)``.  These are the calibrated
#: policy values the score-change law governs: a recalibration moves the
#: canonical ``params_digest`` — and with it the run identity — without any
#: manual revision bump.  The risk bands ride along because the elevated /
#: extreme populations the formula weighs are counted against them.
EVALUATION_HEALTH_PARAM_OWNERS: Final[tuple[tuple[str, str], ...]] = (
    ("cohesion_risk_medium_max", "COHESION_RISK_MEDIUM_MAX"),
    (
        "complexity_elevated_reference_permille",
        "HEALTH_COMPLEXITY_ELEVATED_REFERENCE_PERMILLE",
    ),
    ("complexity_elevated_weight", "HEALTH_COMPLEXITY_ELEVATED_WEIGHT"),
    (
        "complexity_extreme_reference_permille",
        "HEALTH_COMPLEXITY_EXTREME_REFERENCE_PERMILLE",
    ),
    ("complexity_extreme_weight", "HEALTH_COMPLEXITY_EXTREME_WEIGHT"),
    (
        "complexity_outlier_saturation_multiple",
        "HEALTH_COMPLEXITY_OUTLIER_SATURATION_MULTIPLE",
    ),
    ("complexity_outlier_weight", "HEALTH_COMPLEXITY_OUTLIER_WEIGHT"),
    ("complexity_risk_low_max", "COMPLEXITY_RISK_LOW_MAX"),
    ("complexity_risk_medium_max", "COMPLEXITY_RISK_MEDIUM_MAX"),
    (
        "complexity_tail_saturation_multiple",
        "HEALTH_COMPLEXITY_TAIL_SATURATION_MULTIPLE",
    ),
    ("complexity_typical_weight", "HEALTH_COMPLEXITY_TYPICAL_WEIGHT"),
    (
        "coupling_elevated_reference_permille",
        "HEALTH_COUPLING_ELEVATED_REFERENCE_PERMILLE",
    ),
    ("coupling_elevated_weight", "HEALTH_COUPLING_ELEVATED_WEIGHT"),
    (
        "coupling_extreme_reference_permille",
        "HEALTH_COUPLING_EXTREME_REFERENCE_PERMILLE",
    ),
    ("coupling_extreme_weight", "HEALTH_COUPLING_EXTREME_WEIGHT"),
    (
        "coupling_outlier_saturation_multiple",
        "HEALTH_COUPLING_OUTLIER_SATURATION_MULTIPLE",
    ),
    ("coupling_outlier_weight", "HEALTH_COUPLING_OUTLIER_WEIGHT"),
    ("coupling_risk_low_max", "COUPLING_RISK_LOW_MAX"),
    ("coupling_risk_medium_max", "COUPLING_RISK_MEDIUM_MAX"),
    ("coupling_tail_saturation_multiple", "HEALTH_COUPLING_TAIL_SATURATION_MULTIPLE"),
    ("coupling_typical_weight", "HEALTH_COUPLING_TYPICAL_WEIGHT"),
    ("dependency_cycle_penalty", "HEALTH_DEPENDENCY_CYCLE_PENALTY"),
    ("dependency_deferred_cycle_penalty", "HEALTH_DEPENDENCY_DEFERRED_CYCLE_PENALTY"),
    ("dependency_depth_avg_multiplier", "HEALTH_DEPENDENCY_DEPTH_AVG_MULTIPLIER"),
    ("dependency_depth_level_penalty", "HEALTH_DEPENDENCY_DEPTH_LEVEL_PENALTY"),
    ("weights", "HEALTH_WEIGHTS"),
)


class ReportIdentityRegistryError(ValueError):
    """An unregistered family reached the semantic identity."""


def spec_family(spec: ProducerSpec) -> str:
    return str(spec["family"])


def spec_identity_domain(spec: ProducerSpec) -> str:
    return str(spec["identity_domain"])


def spec_activation(spec: ProducerSpec) -> str:
    return str(spec["activation"])


def spec_enabling_lane(spec: ProducerSpec) -> str | None:
    lane = spec.get("enabling_lane")
    return lane if isinstance(lane, str) else None


def spec_identity_keys(spec: ProducerSpec) -> tuple[str, ...]:
    keys = spec["identity_keys"]
    assert isinstance(keys, tuple)
    return tuple(str(key) for key in keys)


def all_identity_keys() -> frozenset[str]:
    """Every key any registered producer glues entity identity into."""

    return frozenset(
        key for spec in REPORT_SEMANTIC_PRODUCERS for key in spec_identity_keys(spec)
    )


def spec_revision_owners(spec: ProducerSpec) -> tuple[tuple[str, str], ...]:
    owners = spec["revision_owners"]
    assert isinstance(owners, tuple)
    pairs: list[tuple[str, str]] = []
    for pair in owners:
        assert isinstance(pair, tuple) and len(pair) == 2
        pairs.append((str(pair[0]), str(pair[1])))
    return tuple(pairs)


def analysis_families() -> tuple[str, ...]:
    return tuple(
        spec_family(spec)
        for spec in REPORT_SEMANTIC_PRODUCERS
        if spec_identity_domain(spec) == "analysis"
    )


def evaluation_families() -> tuple[str, ...]:
    return tuple(
        spec_family(spec)
        for spec in REPORT_SEMANTIC_PRODUCERS
        if spec_identity_domain(spec) == "evaluation"
    )


def producer_spec(family: str) -> ProducerSpec:
    """The registered owner of one family; an unknown family is a typed
    refusal, never a silent pass-through (dispatch is total)."""

    for spec in REPORT_SEMANTIC_PRODUCERS:
        if spec_family(spec) == family:
            return spec
    raise ReportIdentityRegistryError(
        f"semantic family {family!r} has no registered producer; "
        "register it in codeclone.contracts.report_identity before it "
        "can be uttered by a report"
    )


def _live_constant(name: str) -> object:
    import codeclone.contracts as _contracts

    return getattr(_contracts, name)


def registered_revisions(spec: ProducerSpec) -> dict[str, str]:
    """The registry's own answer for a family's revisions, resolved live.

    Used only for families whose containers do not utter a revision; a
    container-uttered revision always wins (realized beats registered).
    """

    return {
        semantic_name: str(_live_constant(constant_name))
        for semantic_name, constant_name in spec_revision_owners(spec)
    }


def realized_health_params() -> dict[str, object]:
    """The live health-policy parameters, uttered into every document that
    computed a health verdict and digested there."""

    return {
        semantic_name: _live_constant(constant_name)
        for semantic_name, constant_name in EVALUATION_HEALTH_PARAM_OWNERS
    }


__all__ = [
    "EVALUATION_HEALTH_PARAM_OWNERS",
    "PRODUCER_STATE_COMPLETE",
    "PRODUCER_STATE_DISABLED",
    "REPORT_SEMANTIC_PRODUCERS",
    "ProducerActivation",
    "ProducerSpec",
    "ReportIdentityRegistryError",
    "all_identity_keys",
    "analysis_families",
    "evaluation_families",
    "producer_spec",
    "realized_health_params",
    "registered_revisions",
    "spec_activation",
    "spec_enabling_lane",
    "spec_family",
    "spec_identity_domain",
    "spec_identity_keys",
    "spec_revision_owners",
]
