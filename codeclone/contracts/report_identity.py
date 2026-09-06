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
#: ``document_sections`` the canonical report sections whose WHOLE content
#:                       is this family's identity projection (identity v3):
#:                       the containers the producer writes and the metric
#:                       containers it draws its verdicts from.  Composed
#:                       from the producer contract, never from the current
#:                       JSON; the owner in
#:                       ``codeclone.report.document.family_projection`` walks
#:                       them and applies the key classes below.  Every
#:                       section has exactly one owner across the whole
#:                       registry, and every registered user-visible section
#:                       (``findings.groups.*`` and every
#:                       ``metrics.registry.METRIC_FAMILIES`` report section)
#:                       has one: the ratchet is total over the producers,
#:                       not over one findings projection.  An analysis
#:                       family's projection is digested at the analysis tier
#:                       (comparison statements routed out); an evaluation
#:                       family's is digested whole at the evaluation tier.
#: ``uttered_revision``  optional ``(semantic_name, section, path)``: where
#:                       the producer's own container utters the revision it
#:                       derived its facts under.  Realized beats registered:
#:                       a present utterance is the realized contract, and
#:                       verification cross-checks it against the realized
#:                       copy.  Absent for families whose containers utter
#:                       none (their registry constant is the answer).
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
        "family": "api_surface",
        "identity_keys": (),
        "identity_domain": "analysis",
        "revision_owners": (
            ("api_surface_signature", "API_SURFACE_SIGNATURE_VERSION"),
        ),
        # ``report.meta.computed_metric_families`` withholds the family unless
        # ``--api-surface`` was passed, so the declaration witnesses the
        # opt-in; the container's ``summary.enabled`` says the same.
        "activation": "metrics",
        # ``core.api_surface_payload``: the visible public symbols of every
        # module (``record_kind == "symbol"``) and, after the baseline diff,
        # one ``breaking_change`` row per new breaking change.  The symbol
        # rows are the api_surface observation lane's statements; the
        # breaking rows and the summary's ``added`` / ``breaking`` /
        # ``baseline_diff_available`` are comparison-domain (declared below).
        "document_sections": ("metrics.families.api_surface",),
    },
    {
        "family": "authority",
        "identity_keys": ("id",),
        "identity_domain": "analysis",
        "revision_owners": (("authority_analysis", "AUTHORITY_ANALYSIS_REVISION"),),
        "activation": "lane",
        "enabling_lane": "semantic_authority",
        # ``source_facts.semantic`` carries the SemanticAuthorityResult (the
        # observation); the metrics container is the STATEMENT projection the
        # user reads, and it utters what the observation does not — the
        # candidate level, score and ranking kind, the registry and the
        # contract IR (``core.metrics_payload._semantic_authority_payload``).
        # Measured 2026-09-05 on a real document: 52 key patterns of that
        # container differed on the wire while every tier stayed the same.
        "document_sections": (
            "findings.groups.authority",
            "metrics.families.semantic_authority",
        ),
    },
    {
        "family": "clones",
        "identity_keys": ("fingerprint", "group_key", "id"),
        "identity_domain": "analysis",
        "revision_owners": (("clone_fingerprint", "BASELINE_FINGERPRINT_VERSION"),),
        "activation": "always",
        "document_sections": ("findings.groups.clones",),
    },
    {
        "family": "coverage_adoption",
        "identity_keys": (),
        "identity_domain": "analysis",
        "revision_owners": (
            ("adoption_coverage_policy", "ADOPTION_COVERAGE_POLICY_VERSION"),
        ),
        "activation": "metrics",
        # ``core.coverage_payload._coverage_adoption_rows``: per-module typing
        # and docstring adoption counts and permilles, summed in the summary
        # by ``core.metrics_payload``.  The three ``*_delta`` fields and
        # ``baseline_diff_available`` are copied from the metrics diff:
        # comparison-domain, declared below.
        "document_sections": ("metrics.families.coverage_adoption",),
    },
    {
        "family": "coverage_join",
        "identity_keys": (),
        "identity_domain": "analysis",
        # No constant witnesses the join algorithm (``metrics.coverage_join``:
        # path resolution, unit matching, permille) and the container utters
        # no revision.  Reported, not invented: the family is registered
        # without a revision owner until one exists.
        "revision_owners": (),
        # ``report.meta.computed_metric_families`` names the family iff the
        # join ran (the payload carries the container only then), which is
        # also the canonical population's witness (``coverage_join`` is
        # ``not_executed`` on every run without ``--coverage``).
        "activation": "metrics",
        # ``metrics.coverage_join.build_coverage_join``: the external
        # Cobertura report joined onto the analysis units — a current-run
        # signal, never baseline truth.  Its analysis statements are the
        # joined line counts, permilles and statuses per unit and overall;
        # the hotspot verdicts are decided by the ``coverage_min`` GATE
        # threshold together with the risk band words and are classified out
        # below as evaluation-policy output.  Until identity v3 the container
        # rode ``design`` because that family's findings utter the hotspot
        # rows; the producer that writes a container is its owner.
        "document_sections": ("metrics.families.coverage_join",),
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
        # The findings builder reads its verdicts from the metrics family
        # (``_build_dead_code_groups``), and that family carries the lanes no
        # finding projects: ``unresolved`` (reason, reachability, witness),
        # ``suppressed_items``, ``unresolved_overrides``, ``live_root_reasons``
        # and the summary — all produced by ``core.metrics_payload``.
        "document_sections": (
            "findings.groups.dead_code",
            "metrics.families.dead_code",
        ),
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
        # ``_build_design_groups`` derives its findings from these four
        # metric families; below the thresholds the rows exist only here.
        # It also draws coverage hotspot findings from ``coverage_join``,
        # whose container has its own registered owner above: a section is
        # owned by the producer that writes it, and the findings drawn from
        # it are owned here.
        "document_sections": (
            "findings.groups.design",
            "metrics.families.complexity",
            "metrics.families.coupling",
            "metrics.families.cohesion",
            "metrics.families.dependencies",
        ),
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
        "document_sections": (),
    },
    {
        "family": "health",
        "identity_keys": (),
        "identity_domain": "evaluation",
        "revision_owners": (("health_algorithm", "HEALTH_ALGORITHM_REVISION"),),
        "activation": "metrics",
        # Digested whole by the EVALUATION tier through the same projection
        # owner: the score, grade, dimensions, population and baseline delta
        # the producer utters (``metrics.health.health_report_fields``).
        "document_sections": ("metrics.families.health",),
    },
    {
        "family": "near_miss",
        "identity_keys": ("pair_key",),
        "identity_domain": "analysis",
        "revision_owners": (("near_miss", "NEAR_MISS_ALGORITHM_REVISION"),),
        "uttered_revision": (
            "near_miss",
            "findings.groups.near_miss",
            "algorithm_revision",
        ),
        "activation": "opt_in",
        "document_sections": ("findings.groups.near_miss",),
    },
    {
        "family": "overloaded_modules",
        "identity_keys": (),
        "identity_domain": "analysis",
        # No constant owns this producer's revision: the container utters it
        # (``detection.version``) and realized beats registered.
        "revision_owners": (),
        "uttered_revision": (
            "overloaded_modules_detection",
            "metrics.families.overloaded_modules",
            "detection.version",
        ),
        "activation": "metrics",
        # ``metrics.overloaded_modules.build_overloaded_modules_payload``:
        # per-module size / dependency / shape facts, their project-relative
        # percentile scores and the candidate verdicts the producer's own
        # literal thresholds decide.  No registered evaluation parameter is
        # involved, so the verdicts are the producer's statements; the
        # ``detection`` block is its realized contract, uttered.
        "document_sections": ("metrics.families.overloaded_modules",),
    },
    {
        "family": "renamed_structure",
        "identity_keys": ("fingerprint", "group_key"),
        "identity_domain": "analysis",
        "revision_owners": (
            ("renamed_structure", "RENAMED_STRUCTURE_ALGORITHM_REVISION"),
        ),
        "uttered_revision": (
            "renamed_structure",
            "findings.groups.renamed_structure",
            "algorithm_revision",
        ),
        "activation": "opt_in",
        "document_sections": ("findings.groups.renamed_structure",),
    },
    {
        "family": "security_surfaces",
        "identity_keys": (),
        "identity_domain": "analysis",
        "revision_owners": (
            ("security_surface_catalog", "SECURITY_SURFACE_CATALOG_VERSION"),
        ),
        "activation": "metrics",
        # ``analysis.security_surfaces.project_security_surfaces`` over the
        # semantic events, published by ``core.security_surfaces_payload``: a
        # report-only inventory of security-relevant call sites.  No
        # observation lane carries these events, so this container is the
        # statements' only spelling.
        "document_sections": ("metrics.families.security_surfaces",),
    },
    {
        "family": "structural",
        "identity_keys": ("id",),
        "identity_domain": "analysis",
        "revision_owners": (
            ("structural_findings_catalog", "STRUCTURAL_FINDINGS_CATALOG_VERSION"),
        ),
        "activation": "always",
        "document_sections": ("findings.groups.structural",),
    },
)

# ---------------------------------------------------------------------------
# Identity v3: how the projection owner classifies the keys it meets.
#
# The default for every key is SEMANTIC — it enters the family identity by
# construction.  Only a declaration below takes a key out, and each declaration
# names one of the ratified exclusion classes.  ``comparison`` is not an
# exclusion: the key is routed to the comparison-tier projection of the same
# family, where a baseline-derived statement has its natural tier.
# ---------------------------------------------------------------------------

#: Stays in the analysis projection (the default; declared only to make a
#: contested classification an explicit, single-line, reversible statement).
KEY_CLASS_SEMANTIC: Final = "semantic"
#: Renderer inputs ("Presentation facts"): presentation never computes.
KEY_CLASS_PRESENTATION: Final = "presentation"
#: Bare source positions and physical extents: the analyzer invariant (a
#: comment edit is invisible to analysis, and MCP patch verification rests on
#: that equality) requires a finding whose only movement is a shifted location
#: — or a module whose only change is a longer text — to keep its identity.
#: A position a producer GLUES into an identity key is identity, not
#: provenance, and the glued key is never in this class.
KEY_CLASS_NAVIGATION_PROVENANCE: Final = "navigation_provenance"
#: Where an input artifact lived (a path), as opposed to what it said.
KEY_CLASS_CONFIGURATION_PROVENANCE: Final = "configuration_provenance"
#: A word decided by a registered EVALUATION parameter (the risk bands live
#: in ``EVALUATION_HEALTH_PARAM_OWNERS``; the coverage hotspot threshold is
#: the ``coverage_min`` gate in ``gate_thresholds_digest``), or the echo of
#: that parameter itself: its natural tier is evaluation, where the policy is
#: digested as a realized parameter, so hashing it at the analysis tier would
#: let a band recalibration or a gate change move ANALYSIS.
KEY_CLASS_EVALUATION_POLICY_OUTPUT: Final = "evaluation_policy_output"
#: A fact this container repeats for its reader whose semantic owner is the
#: ANALYSIS tier of the same document.  The opposite direction from
#: ``comparison``: that class routes a statement UP to the tier that owns it,
#: this one records that the owning tier is already BELOW and needs nothing
#: routed to it.  The excluded key stays on the wire and stays true — it is
#: withheld from this family's preimage only so one fact has exactly one
#: identity-bearing carrier.  Deliberately narrow: it licenses withholding a
#: key only where an analysis-tier owner demonstrably states the same fact,
#: never a key a producer merely considers uninteresting.
KEY_CLASS_CONSUMED_ANALYSIS_FACT: Final = "consumed_analysis_fact"
#: A baseline-derived statement (amendment 3: novelty, delta semantics are
#: COMPARISON-domain), routed to the comparison-tier projection.
KEY_CLASS_COMPARISON: Final = "comparison"

KEY_CLASSES: Final[tuple[str, ...]] = (
    KEY_CLASS_SEMANTIC,
    KEY_CLASS_PRESENTATION,
    KEY_CLASS_NAVIGATION_PROVENANCE,
    KEY_CLASS_CONFIGURATION_PROVENANCE,
    KEY_CLASS_EVALUATION_POLICY_OUTPUT,
    KEY_CLASS_CONSUMED_ANALYSIS_FACT,
    KEY_CLASS_COMPARISON,
)

#: Keys classified the same way in every family at any depth.
UNIVERSAL_KEY_CLASSES: Final[Mapping[str, str]] = {
    "display_facts": KEY_CLASS_PRESENTATION,
    "start_line": KEY_CLASS_NAVIGATION_PROVENANCE,
    "end_line": KEY_CLASS_NAVIGATION_PROVENANCE,
    "differing_start_line": KEY_CLASS_NAVIGATION_PROVENANCE,
    "differing_end_line": KEY_CLASS_NAVIGATION_PROVENANCE,
    # ``_clone_novelty`` / ``_entity_novelty`` (report.document._common) are
    # the one owner of both words; every findings family utters them.
    "novelty": KEY_CLASS_COMPARISON,
    "novelty_reason": KEY_CLASS_COMPARISON,
    # ``threshold_risk`` over COMPLEXITY_RISK_* / COUPLING_RISK_* /
    # COHESION_RISK_MEDIUM_MAX (metrics.complexity / coupling / cohesion).
    "risk": KEY_CLASS_EVALUATION_POLICY_OUTPUT,
}

#: Keys classified at one path of one section of one family: ``(section,
#: path)`` with ``[]`` for a sequence element.  A declaration that no
#: document utters is a dead witness; the acceptance corpus pins every
#: declaration observed over the maximal document.
SCOPED_KEY_CLASSES: Final[Mapping[str, Mapping[tuple[str, str], str]]] = {
    "api_surface": {
        # ``core.metrics_payload`` fills these from the metrics diff.
        (
            "metrics.families.api_surface",
            "summary.baseline_diff_available",
        ): KEY_CLASS_COMPARISON,
        ("metrics.families.api_surface", "summary.added"): KEY_CLASS_COMPARISON,
        ("metrics.families.api_surface", "summary.breaking"): KEY_CLASS_COMPARISON,
    },
    "coverage_adoption": {
        # ``core.metrics_payload`` copies these from the metrics diff.
        (
            "metrics.families.coverage_adoption",
            "summary.baseline_diff_available",
        ): KEY_CLASS_COMPARISON,
        (
            "metrics.families.coverage_adoption",
            "summary.param_delta",
        ): KEY_CLASS_COMPARISON,
        (
            "metrics.families.coverage_adoption",
            "summary.return_delta",
        ): KEY_CLASS_COMPARISON,
        (
            "metrics.families.coverage_adoption",
            "summary.docstring_delta",
        ): KEY_CLASS_COMPARISON,
    },
    "coverage_join": {
        # The Cobertura file's path (``coverage_join.summary.source``): where
        # the coverage came from, not what it said.
        (
            "metrics.families.coverage_join",
            "summary.source",
        ): KEY_CLASS_CONFIGURATION_PROVENANCE,
        # ``MetricGateConfig.coverage_min`` (``--coverage-min``, the coverage
        # GATE, digested at the evaluation tier in ``gate_thresholds_digest``)
        # is what ``core.pipeline`` hands the join as its hotspot threshold;
        # the summary echoes it, and the two hotspot verdicts per unit and
        # their two counts are decided by it together with the risk band
        # words classified above (``metrics.coverage_join._is_*_hotspot``).
        (
            "metrics.families.coverage_join",
            "summary.hotspot_threshold_percent",
        ): KEY_CLASS_EVALUATION_POLICY_OUTPUT,
        (
            "metrics.families.coverage_join",
            "summary.coverage_hotspots",
        ): KEY_CLASS_EVALUATION_POLICY_OUTPUT,
        (
            "metrics.families.coverage_join",
            "summary.scope_gap_hotspots",
        ): KEY_CLASS_EVALUATION_POLICY_OUTPUT,
        (
            "metrics.families.coverage_join",
            "items[].coverage_hotspot",
        ): KEY_CLASS_EVALUATION_POLICY_OUTPUT,
        (
            "metrics.families.coverage_join",
            "items[].scope_gap_hotspot",
        ): KEY_CLASS_EVALUATION_POLICY_OUTPUT,
    },
    "overloaded_modules": {
        # ``analysis.units`` counts ``len(source_lines)`` — the PHYSICAL line
        # count, comment lines included — and ``metrics.overloaded_modules``
        # publishes it as ``loc``.  Measured 2026-09-05 (the MCP analyzer
        # invariant probes): a comment-only edit moved it and with it the run
        # id.  A text extent is the same kind of fact as a bare position; the
        # structural counts beside it (functions, methods, classes, callable
        # count, complexity, fan-in/out) stay semantic, and the percentile
        # ranks derived over ``loc`` stay semantic as the producer's verdict.
        (
            "metrics.families.overloaded_modules",
            "items[].loc",
        ): KEY_CLASS_NAVIGATION_PROVENANCE,
    },
    "health": {
        # ``compute_health`` does not decide this word: it asks
        # ``contracts.observed_population``, which reads it off the run's own
        # discovery counters, and the ANALYSIS population block states the
        # same answer from the same owner
        # (``report.document.integrity._population``, key ``observed``).
        # Health displays it — ``population_carries_score`` is why the score
        # may be withheld — and displaying is not owning.  Kept semantic, it
        # would be the fact's SECOND identity-bearing carrier, and the two
        # could then disagree inside one preimage.  A population change still
        # moves the evaluation tier, transitively: evaluation chains the
        # comparison digest, which chains ``analysis_facts``.
        (
            "metrics.families.health",
            "summary.population",
        ): KEY_CLASS_CONSUMED_ANALYSIS_FACT,
    },
    "dead_code": {
        # ``metrics.py`` copies these from the baseline comparison
        # (``baseline_diff_available``, ``new_items``): comparison-domain.
        (
            "metrics.families.dead_code",
            "summary.baseline_diff_available",
        ): KEY_CLASS_COMPARISON,
        ("metrics.families.dead_code", "summary.new_items"): KEY_CLASS_COMPARISON,
    },
    "design": {
        # E-N+2P over the complete CFG (core.metrics_payload): its producer
        # calls it "diagnostic — never health input, never a gate", which
        # names evaluation CONSUMERS, not presentation, ordering, provenance
        # or evaluation output.  Under the four ratified exclusions it is
        # semantic; whether "diagnostic" becomes a fifth class is the
        # maintainer's ruling — flip this one line.
        (
            "metrics.families.complexity",
            "items[].cfg_cyclomatic_complexity",
        ): KEY_CLASS_SEMANTIC,
        # ``len(high_risk_functions)`` / ``len(high_risk_classes)`` /
        # ``len(low_cohesion_classes)`` (metrics.registry): counts over the
        # band words classified above.
        (
            "metrics.families.complexity",
            "summary.high_risk",
        ): KEY_CLASS_EVALUATION_POLICY_OUTPUT,
        (
            "metrics.families.coupling",
            "summary.high_risk",
        ): KEY_CLASS_EVALUATION_POLICY_OUTPUT,
        (
            "metrics.families.cohesion",
            "summary.low_cohesion",
        ): KEY_CLASS_EVALUATION_POLICY_OUTPUT,
        # Baseline comparison copies (``metrics.py``): comparison-domain.
        (
            "metrics.families.complexity",
            "summary.baseline_diff_available",
        ): KEY_CLASS_COMPARISON,
        ("metrics.families.complexity", "summary.new_high_risk"): KEY_CLASS_COMPARISON,
        (
            "metrics.families.coupling",
            "summary.baseline_diff_available",
        ): KEY_CLASS_COMPARISON,
        ("metrics.families.coupling", "summary.new_high_risk"): KEY_CLASS_COMPARISON,
        (
            "metrics.families.dependencies",
            "summary.baseline_diff_available",
        ): KEY_CLASS_COMPARISON,
        ("metrics.families.dependencies", "summary.new_cycles"): KEY_CLASS_COMPARISON,
        (
            "metrics.families.dependencies",
            "summary.new_import_cycles",
        ): KEY_CLASS_COMPARISON,
        (
            "metrics.families.dependencies",
            "summary.new_deferred_cycles",
        ): KEY_CLASS_COMPARISON,
        # The import statement's line (``dependencies.edge_list[].line``):
        # a bare position, same class as the span keys above.
        (
            "metrics.families.dependencies",
            "items[].line",
        ): KEY_CLASS_NAVIGATION_PROVENANCE,
    },
}

#: Rows classified WHOLE by the value of one of their keys: ``(section,
#: path)`` of the sequence element, then ``(discriminator_key, {value:
#: class})``.  A row whose discriminator names a class leaves the analysis
#: projection as one statement (routed whole when the class is
#: ``comparison``); every other row is walked as usual.  A producer that
#: interleaves two tiers in one list is declared here rather than split by
#: key, because a baseline-derived ROW is a comparison statement as a whole
#: — projecting its remaining keys at the analysis tier would let the
#: baseline move the tier meant to be the fixed point.
SCOPED_ROW_CLASSES: Final[
    Mapping[str, Mapping[tuple[str, str], tuple[str, Mapping[str, str]]]]
] = {
    "api_surface": {
        # ``core.metrics_payload`` appends one ``breaking_change`` row per new
        # breaking change of the baseline diff to the symbol rows.
        ("metrics.families.api_surface", "items[]"): (
            "record_kind",
            {"breaking_change": KEY_CLASS_COMPARISON},
        ),
    },
}

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


def spec_document_sections(spec: ProducerSpec) -> tuple[str, ...]:
    sections = spec["document_sections"]
    assert isinstance(sections, tuple)
    return tuple(str(section) for section in sections)


def spec_uttered_revision(spec: ProducerSpec) -> tuple[str, str, str] | None:
    """``(semantic_name, section, path)`` of the revision the producer's own
    container utters, or ``None`` when its containers utter none."""

    declared = spec.get("uttered_revision")
    if declared is None:
        return None
    assert isinstance(declared, tuple) and len(declared) == 3
    return (str(declared[0]), str(declared[1]), str(declared[2]))


def registered_families() -> tuple[str, ...]:
    """Every registered family, analysis and evaluation, in registry order."""

    return tuple(spec_family(spec) for spec in REPORT_SEMANTIC_PRODUCERS)


def non_semantic_key_names() -> frozenset[str]:
    """Every key name any declaration takes out of an analysis projection —
    universal or scoped, excluded or routed.  The census law: this set and
    the identity keys never intersect."""

    names = {
        key for key, cls in UNIVERSAL_KEY_CLASSES.items() if cls != KEY_CLASS_SEMANTIC
    }
    for declarations in SCOPED_KEY_CLASSES.values():
        for (_section, path), cls in declarations.items():
            if cls != KEY_CLASS_SEMANTIC:
                names.add(path.rsplit(".", 1)[-1])
    return frozenset(names)


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
    "KEY_CLASSES",
    "KEY_CLASS_COMPARISON",
    "KEY_CLASS_CONFIGURATION_PROVENANCE",
    "KEY_CLASS_CONSUMED_ANALYSIS_FACT",
    "KEY_CLASS_EVALUATION_POLICY_OUTPUT",
    "KEY_CLASS_NAVIGATION_PROVENANCE",
    "KEY_CLASS_PRESENTATION",
    "KEY_CLASS_SEMANTIC",
    "PRODUCER_STATE_COMPLETE",
    "PRODUCER_STATE_DISABLED",
    "REPORT_SEMANTIC_PRODUCERS",
    "SCOPED_KEY_CLASSES",
    "SCOPED_ROW_CLASSES",
    "UNIVERSAL_KEY_CLASSES",
    "ProducerActivation",
    "ProducerSpec",
    "ReportIdentityRegistryError",
    "all_identity_keys",
    "analysis_families",
    "evaluation_families",
    "non_semantic_key_names",
    "producer_spec",
    "realized_health_params",
    "registered_families",
    "registered_revisions",
    "spec_activation",
    "spec_document_sections",
    "spec_enabling_lane",
    "spec_family",
    "spec_identity_domain",
    "spec_identity_keys",
    "spec_revision_owners",
    "spec_uttered_revision",
]
