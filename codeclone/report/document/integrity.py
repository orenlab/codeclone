# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Canonical report digest hierarchy and verification owner.

Two generations live here, named by ``integrity.semantic_identity_version``:

* **Generation 1** (no marker) hashed the source facts, the baseline
  projection and the gate request.  Findings tiers, policy parameters and
  evaluation outputs were outside the preimage: five measured
  (tree x config x engine) states shared one ``run_id``
  (probes p1/p2b/p2c/p3/health, 2026-08-31).  Documents of that generation
  keep verifying under their own rules — a generation is interpreted, never
  reinterpreted.
* **Generation 2** (RULING-2026-08-31) adds the analysis population, the
  realized producer contracts and a canonical digest per EXECUTED semantic
  family, composing them through the ratified hierarchy::

      ANALYSIS   = H(scope, population, realized analysis contracts,
                     analysis family digests)
      COMPARISON = H(ANALYSIS, baseline projection, realized comparison
                     contract)
      EVALUATION = H(COMPARISON, evaluation, realized evaluation contract,
                     evaluation family digests)
      run_id     = EVALUATION

Verification is document-internal in both generations: no check compares a
document against this process's constants, so a document produced by another
engine generation stays honestly verifiable.  Live policy values (the health
parameters) are uttered into the document at build time and checked there
through their ``params_digest``; container-uttered values (a tier's
``algorithm_revision``, its policy budget) are cross-checked against their
realized copies, because one fact spelled twice in one document must agree.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from dataclasses import asdict
from hashlib import sha256

from ...cache.integrity import canonical_json_bytes
from ...contracts import (
    GATE_ALGORITHM_REVISION,
    GATE_LANE_MATRIX_VERSION,
    HEALTH_ALGORITHM_REVISION,
    HEALTH_INPUT_MANIFEST_VERSION,
    REPORT_ANALYSIS_FACTS_DIGEST_DOMAIN,
    REPORT_ANALYSIS_IDENTITY_DOMAIN_V2,
    REPORT_COMPARISON_DIGEST_DOMAIN,
    REPORT_COMPARISON_IDENTITY_DOMAIN_V2,
    REPORT_ENVELOPE_DIGEST_DOMAIN,
    REPORT_EVALUATION_DIGEST_DOMAIN,
    REPORT_EVALUATION_IDENTITY_DOMAIN_V2,
    REPORT_FAMILY_DIGEST_DOMAIN_V2,
    REPORT_SEMANTIC_IDENTITY_VERSION,
)
from ...contracts.report_identity import (
    PRODUCER_STATE_COMPLETE,
    PRODUCER_STATE_DISABLED,
    REPORT_SEMANTIC_PRODUCERS,
    ProducerSpec,
    producer_spec,
    realized_health_params,
    registered_revisions,
    spec_activation,
    spec_enabling_lane,
    spec_family,
    spec_identity_domain,
    spec_revision_owners,
)
from ...models import (
    EvaluationContract,
    ObservationLaneName,
    ReportDigest,
    ReportDigestKind,
)
from ...utils.coerce import as_mapping as _as_mapping
from ..gates.evaluator import (
    HEALTH_INPUT_LANES,
    GateResult,
    MetricGateConfig,
    active_gate_lane_requirements,
)

_DIGEST_VERSION = "1"

#: The population's file receipt: which discovery counters are semantic
#: statements about the analyzed universe.  Copied by name so a counter added
#: to the inventory payload later does not silently join the identity.
#: ``analyzed``, ``cached`` and ``source_io_skipped`` are deliberately
#: absent: how many files were served warm versus re-parsed — and whether
#: their source bytes were read at all on this particular run — is execution
#: provenance.  The measured d2_warm probe pinned that a warm cache keeps
#: the run identity, and the cache-provenance test keeps that boundary
#: honest.  What remains is the semantic truncation witness: how many files
#: the universe held and how many were refused admission.
_POPULATION_FILE_COUNTERS = (
    "total_found",
    "skipped",
    "unsupported_construct_skipped",
)

#: ``meta.baseline`` fields that are comparison semantics.  Deliberately
#: excluded: ``path`` (configuration location), ``python_tag`` (provenance —
#: measured identical observations across 3.10..3.14), ``generator_name`` /
#: ``generator_version`` (provenance).
_COMPARISON_BASELINE_FIELDS = (
    "fingerprint_version",
    "loaded",
    "payload_sha256",
    "payload_sha256_verified",
    "schema_version",
    "status",
)
_COMPARISON_METRICS_BASELINE_FIELDS = (
    "loaded",
    "payload_sha256",
    "schema_version",
    "status",
)


def _digest_wire(value: ReportDigest) -> dict[str, object]:
    return {
        "kind": value.kind,
        "algorithm": value.algorithm,
        "digest_version": value.digest_version,
        "value": value.value,
    }


def _digest(
    *,
    domain: str,
    kind: ReportDigestKind,
    payload: object,
) -> ReportDigest:
    digest = sha256()
    digest.update(domain.encode("utf-8"))
    digest.update(canonical_json_bytes(payload))
    return ReportDigest(
        kind=kind,
        algorithm="sha256",
        digest_version="1",
        value=digest.hexdigest(),
    )


def _observation_wire(value: str) -> dict[str, object]:
    return {
        "kind": "source_observations",
        "algorithm": "sha256",
        "digest_version": _DIGEST_VERSION,
        "value": value,
    }


def build_evaluation_contract(
    config: MetricGateConfig,
    *,
    enabled_lanes: tuple[ObservationLaneName, ...] = (),
) -> EvaluationContract:
    """Build the report-owned evaluation identity from normalized gate policy.

    The two algorithm revisions come from their contract owners
    (``HEALTH_ALGORITHM_REVISION`` / ``GATE_ALGORITHM_REVISION``): until
    identity v2 they were inline ``"1"`` literals here — witnesses no
    constant owned, so no formula change had a lever to move them.
    """

    thresholds_digest = sha256(canonical_json_bytes(asdict(config))).hexdigest()
    return EvaluationContract(
        health_algorithm_revision=HEALTH_ALGORITHM_REVISION,
        gate_algorithm_revision=GATE_ALGORITHM_REVISION,
        gate_thresholds_digest=thresholds_digest,
        gate_lane_matrix_version=GATE_LANE_MATRIX_VERSION,
        health_input_manifest_version=HEALTH_INPUT_MANIFEST_VERSION,
        health_input_lanes=tuple(
            lane for lane in HEALTH_INPUT_LANES if lane in frozenset(enabled_lanes)
        ),
        active_gate_lane_requirements=active_gate_lane_requirements(
            config=config,
            enabled_lanes=enabled_lanes,
        ),
    )


def build_evaluation_payload(
    *,
    contract: EvaluationContract,
    config: MetricGateConfig,
    result: GateResult,
) -> dict[str, object]:
    """Project one typed evaluation object without re-evaluating it."""

    return {
        "contract": asdict(contract),
        "request": asdict(config),
        "outcome": {
            "exit_code": result.exit_code,
            "reasons": list(result.reasons),
            "required_lanes": list(result.required_lanes),
            "unavailable_lanes": list(result.unavailable_lanes),
        },
    }


def _comparison_digest_input(baseline: Mapping[str, object]) -> dict[str, object]:
    return {
        "state": baseline.get("state"),
        "baseline_scope_id": baseline.get("baseline_scope_id"),
        "root_digest_or_null": baseline.get("root_digest_or_null"),
        "sorted_lane_trust": baseline.get("sorted_lane_trust"),
        "sorted_novelty_facts": baseline.get("sorted_novelty_facts"),
    }


# ---------------------------------------------------------------------------
# Generation 2: the semantic block (population, realized contracts, family
# digests).  Everything below is computed from the document body alone plus —
# at build time only — the live policy constants that the block itself then
# utters, so verification never needs this process's constants.
# ---------------------------------------------------------------------------


def _params_digest(params: Mapping[str, object]) -> str:
    return sha256(canonical_json_bytes(dict(params))).hexdigest()


#: Keys a family digest never hashes.  ``display_facts`` are renderer inputs
#: ("Presentation facts" in the markdown/text renderers) — presentation never
#: computes, so it never names a run.  The four line-span keys are navigation
#: provenance: the analyzer invariant (a Python comment edit is invisible to
#: analysis, and MCP patch verification rests on that equality) requires a
#: finding whose only movement is a shifted location to keep its identity.
#: Where a producer needs a position to DISAMBIGUATE two entities sharing a
#: qualname it glues the line into its identity key (the F1 precedent;
#: ``near_miss.pair_key`` does exactly that), and glued keys are hashed —
#: bare span fields are not.  The registry declares those glued keys per
#: family (``spec_identity_keys``), and the acceptance corpus pins that this
#: set and that declaration never intersect: an identity-bearing key cannot
#: be declared non-semantic.
_NON_SEMANTIC_PROJECTION_KEYS = frozenset(
    {
        "display_facts",
        "start_line",
        "end_line",
        "differing_start_line",
        "differing_end_line",
    }
)


def _semantic_projection(value: object) -> object:
    """Project a container onto its semantic statements before digesting.

    The prune is recursive because the clone family nests its groups inside
    buckets and every findings family nests members inside groups.
    """

    if isinstance(value, Mapping):
        return {
            key: _semantic_projection(item)
            for key, item in value.items()
            if key not in _NON_SEMANTIC_PROJECTION_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_semantic_projection(item) for item in value]
    return value


def _family_digest_value(family: str, projection: object) -> str:
    digest = sha256()
    digest.update(REPORT_FAMILY_DIGEST_DOMAIN_V2.encode("utf-8"))
    digest.update(family.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(canonical_json_bytes(_semantic_projection(projection)))
    return digest.hexdigest()


def _as_sequence_of_str(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _tier_state(container: Mapping[str, object]) -> str:
    state = container.get("state")
    return state if isinstance(state, str) and state else PRODUCER_STATE_DISABLED


def _producer_state(
    spec: ProducerSpec,
    *,
    groups: Mapping[str, object],
    enabled_lanes: frozenset[str],
    computed_metric_families: frozenset[str],
) -> str:
    activation = spec_activation(spec)
    if activation == "always":
        return PRODUCER_STATE_COMPLETE
    if activation == "lane":
        return (
            PRODUCER_STATE_COMPLETE
            if spec_enabling_lane(spec) in enabled_lanes
            else PRODUCER_STATE_DISABLED
        )
    if activation == "opt_in":
        return _tier_state(_as_mapping(groups.get(spec_family(spec))))
    return (
        PRODUCER_STATE_COMPLETE
        if spec_family(spec) in computed_metric_families
        else PRODUCER_STATE_DISABLED
    )


def _population(
    *,
    meta: Mapping[str, object],
    inventory: Mapping[str, object],
    groups: Mapping[str, object],
    enabled_lanes: frozenset[str],
) -> dict[str, object]:
    computed = frozenset(_as_sequence_of_str(meta.get("computed_metric_families")))
    files_payload = _as_mapping(inventory.get("files"))
    files = {
        name: value
        for name in _POPULATION_FILE_COUNTERS
        if isinstance(value := files_payload.get(name), int)
    }
    producers = {
        spec_family(spec): _producer_state(
            spec,
            groups=groups,
            enabled_lanes=enabled_lanes,
            computed_metric_families=computed,
        )
        for spec in REPORT_SEMANTIC_PRODUCERS
    }
    population: dict[str, object] = {
        "files": files,
        "producers": producers,
    }
    analysis_mode = meta.get("analysis_mode")
    if isinstance(analysis_mode, str) and analysis_mode:
        population["analysis_mode"] = analysis_mode
    return population


def _realized_analysis_contracts(
    *,
    groups: Mapping[str, object],
    meta: Mapping[str, object],
    producers: Mapping[str, object],
    metrics: Mapping[str, object] = {},
) -> dict[str, object]:
    contracts: dict[str, object] = {}
    for spec in REPORT_SEMANTIC_PRODUCERS:
        family = spec_family(spec)
        if spec_identity_domain(spec) != "analysis":
            continue
        if producers.get(family) != PRODUCER_STATE_COMPLETE:
            # Disabled utters no contract: only its population state exists,
            # so a configured revision cannot sneak into the identity.
            continue
        container = _as_mapping(groups.get(family))
        uttered_revision = container.get("algorithm_revision")
        if isinstance(uttered_revision, str) and uttered_revision:
            # Realized beats registered: the container's own utterance is
            # the revision this document derived its facts under.
            semantic_name = spec_revision_owners(spec)[0][0]
            revisions: dict[str, str] = {semantic_name: uttered_revision}
        else:
            revisions = registered_revisions(spec)
        params: dict[str, object] = {}
        if family == "clones":
            params = dict(_as_mapping(meta.get("analysis_profile")))
        elif family == "design":
            params = dict(_as_mapping(meta.get("analysis_thresholds")))
        elif family == "near_miss":
            budget = container.get("max_edit_statements")
            if budget is not None:
                params = {"max_edit_statements": budget}
        elif family == "dead_code":
            # The world contract is a realized parameter of the derivation:
            # two runs over one tree that answer under different worlds
            # utter different verdicts and may not share a name, even when
            # both happen to utter zero dead findings.
            world = _as_mapping(
                _as_mapping(
                    _as_mapping(_as_mapping(metrics).get("families")).get("dead_code")
                ).get("summary")
            ).get("world_contract")
            if isinstance(world, str) and world:
                params = {"world_contract": world}
        contracts[family] = {
            "activation": spec_activation(spec),
            "algorithm_revisions": revisions,
            "params": params,
            "params_digest": _params_digest(params),
        }
    return contracts


def _realized_comparison_contract(meta: Mapping[str, object]) -> dict[str, object]:
    baseline_meta = _as_mapping(meta.get("baseline"))
    metrics_baseline_meta = _as_mapping(meta.get("metrics_baseline"))
    return {
        "baseline": {
            name: baseline_meta.get(name) for name in _COMPARISON_BASELINE_FIELDS
        },
        "metrics_baseline": {
            name: metrics_baseline_meta.get(name)
            for name in _COMPARISON_METRICS_BASELINE_FIELDS
        },
    }


def _realized_evaluation_contract(
    *,
    evaluation: Mapping[str, object],
    producers: Mapping[str, object],
) -> dict[str, object]:
    gates_spec = producer_spec("gates")
    contract = _as_mapping(_as_mapping(evaluation).get("contract"))
    realized: dict[str, object] = {
        "gates": {
            "activation": spec_activation(gates_spec),
            "algorithm_revisions": registered_revisions(gates_spec),
            "thresholds_digest": contract.get("gate_thresholds_digest"),
        }
    }
    if producers.get("health") == PRODUCER_STATE_COMPLETE:
        health_spec = producer_spec("health")
        params = realized_health_params()
        realized["health"] = {
            "activation": spec_activation(health_spec),
            "algorithm_revisions": registered_revisions(health_spec),
            "params": params,
            "params_digest": _params_digest(params),
        }
    return realized


def _analysis_family_digests(
    *,
    groups: Mapping[str, object],
    producers: Mapping[str, object],
) -> dict[str, str]:
    digests: dict[str, str] = {}
    for spec in REPORT_SEMANTIC_PRODUCERS:
        family = spec_family(spec)
        if spec_identity_domain(spec) != "analysis":
            continue
        if producers.get(family) != PRODUCER_STATE_COMPLETE:
            # count = 0 is a completed measurement; a family that never ran
            # has no digest — its absence of execution is population state,
            # never an empty measurement.
            continue
        container = _as_mapping(groups.get(family))
        digests[family] = _family_digest_value(family, container)
    return digests


def _evaluation_family_digests(
    *,
    metrics: Mapping[str, object],
    producers: Mapping[str, object],
) -> dict[str, str]:
    digests: dict[str, str] = {}
    if producers.get("health") == PRODUCER_STATE_COMPLETE:
        health = _as_mapping(
            _as_mapping(_as_mapping(metrics).get("families")).get("health")
        )
        summary = _as_mapping(health.get("summary"))
        digests["health"] = _family_digest_value("health", summary)
    return digests


def _semantic_block(
    *,
    meta: Mapping[str, object],
    inventory: Mapping[str, object],
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
    evaluation: Mapping[str, object],
    source_facts: Mapping[str, object],
) -> dict[str, object]:
    groups = _as_mapping(_as_mapping(findings).get("groups"))
    observation_contract = _as_mapping(source_facts.get("observation_contract"))
    enabled_lanes = frozenset(
        _as_sequence_of_str(observation_contract.get("enabled_lanes"))
    )
    population = _population(
        meta=meta,
        inventory=inventory,
        groups=groups,
        enabled_lanes=enabled_lanes,
    )
    producers = _as_mapping(population.get("producers"))
    return {
        "population": population,
        "realized_contracts": {
            "analysis": _realized_analysis_contracts(
                groups=groups,
                meta=meta,
                producers=producers,
                metrics=metrics,
            ),
            "comparison": _realized_comparison_contract(meta),
            "evaluation": _realized_evaluation_contract(
                evaluation=evaluation,
                producers=producers,
            ),
        },
        "family_digests": {
            "analysis": _analysis_family_digests(
                groups=groups,
                producers=producers,
            ),
            "evaluation": _evaluation_family_digests(
                metrics=metrics,
                producers=producers,
            ),
        },
    }


def _v2_tier_digests(
    *,
    marker: object,
    report_schema_version: str,
    observation: Mapping[str, object],
    source_facts: Mapping[str, object],
    semantic: Mapping[str, object],
    baseline: Mapping[str, object],
    evaluation: Mapping[str, object],
) -> dict[str, ReportDigest]:
    """The one spelling of the generation-2 tier composition.

    Build and verification both call this, so the preimage a document is
    sealed with and the preimage it is checked against cannot drift apart —
    the two-spellings defect class, closed by construction.
    """

    realized = _as_mapping(semantic.get("realized_contracts"))
    family_digests = _as_mapping(semantic.get("family_digests"))
    analysis_facts = _digest(
        domain=REPORT_ANALYSIS_IDENTITY_DOMAIN_V2,
        kind="analysis_facts",
        payload={
            "semantic_identity_version": marker,
            "report_schema_version": report_schema_version,
            "observation_digest": observation,
            "source_facts": source_facts,
            "population": semantic.get("population"),
            "realized_analysis_contracts": realized.get("analysis"),
            "analysis_family_digests": family_digests.get("analysis"),
        },
    )
    comparison = _digest(
        domain=REPORT_COMPARISON_IDENTITY_DOMAIN_V2,
        kind="comparison",
        payload={
            "analysis_facts_digest": _digest_wire(analysis_facts),
            "baseline": _comparison_digest_input(baseline),
            "realized_comparison_contract": realized.get("comparison"),
        },
    )
    evaluation_digest = _digest(
        domain=REPORT_EVALUATION_IDENTITY_DOMAIN_V2,
        kind="evaluation",
        payload={
            "comparison_digest": _digest_wire(comparison),
            "evaluation": evaluation,
            "realized_evaluation_contract": realized.get("evaluation"),
            "evaluation_family_digests": family_digests.get("evaluation"),
        },
    )
    return {
        "analysis_facts": analysis_facts,
        "comparison": comparison,
        "evaluation": evaluation_digest,
    }


def _tier_mismatch(
    digests: Mapping[str, object],
    expected: Mapping[str, ReportDigest],
) -> str | None:
    """The one spelling of the recompute-and-compare loop, both generations."""

    for name in ("analysis_facts", "comparison", "evaluation"):
        actual_value = _digest_value(digests, name)
        if actual_value is None or not hmac.compare_digest(
            actual_value, expected[name].value
        ):
            return f"report {name} digest mismatch"
    return None


def _build_integrity_payload(
    *,
    report_schema_version: str,
    observation_digest: str,
    source_facts: Mapping[str, object],
    baseline: Mapping[str, object],
    evaluation: Mapping[str, object],
    meta: Mapping[str, object],
    inventory: Mapping[str, object],
    findings: Mapping[str, object],
    metrics: Mapping[str, object],
) -> dict[str, object]:
    semantic = _semantic_block(
        meta=meta,
        inventory=inventory,
        findings=findings,
        metrics=metrics,
        evaluation=evaluation,
        source_facts=source_facts,
    )
    observation = _observation_wire(observation_digest)
    tiers = _v2_tier_digests(
        marker=REPORT_SEMANTIC_IDENTITY_VERSION,
        report_schema_version=report_schema_version,
        observation=observation,
        source_facts=source_facts,
        semantic=semantic,
        baseline=baseline,
        evaluation=evaluation,
    )
    return {
        "canonicalization": {
            "version": "3",
            "serializer": "orjson.OPT_SORT_KEYS",
            "envelope_null_sentinel": "integrity.digests.envelope.value",
        },
        "semantic_identity_version": REPORT_SEMANTIC_IDENTITY_VERSION,
        "semantic": semantic,
        "digests": {
            "observation": observation,
            "analysis_facts": _digest_wire(tiers["analysis_facts"]),
            "comparison": _digest_wire(tiers["comparison"]),
            "evaluation": _digest_wire(tiers["evaluation"]),
            "envelope": {
                "kind": "report_envelope",
                "algorithm": "sha256",
                "digest_version": _DIGEST_VERSION,
                "value": None,
            },
        },
    }


def _document_with_envelope_sentinel(
    document: Mapping[str, object],
) -> dict[str, object]:
    payload = dict(document)
    integrity = dict(_as_mapping(document.get("integrity")))
    digests = dict(_as_mapping(integrity.get("digests")))
    envelope = dict(_as_mapping(digests.get("envelope")))
    envelope["value"] = None
    digests["envelope"] = envelope
    integrity["digests"] = digests
    payload["integrity"] = integrity
    return payload


def finalize_envelope_digest(document: dict[str, object]) -> dict[str, object]:
    """Seal the completed report with only its own value replaced by null."""

    envelope = _digest(
        domain=REPORT_ENVELOPE_DIGEST_DOMAIN,
        kind="report_envelope",
        payload=_document_with_envelope_sentinel(document),
    )
    integrity = dict(_as_mapping(document.get("integrity")))
    digests = dict(_as_mapping(integrity.get("digests")))
    digests["envelope"] = _digest_wire(envelope)
    integrity["digests"] = digests
    return {**document, "integrity": integrity}


def _digest_value(
    digests: Mapping[str, object],
    name: str,
) -> str | None:
    value = _as_mapping(digests.get(name)).get("value")
    return value if isinstance(value, str) else None


def _verify_envelope(document: Mapping[str, object]) -> str | None:
    integrity = _as_mapping(document.get("integrity"))
    digests = _as_mapping(integrity.get("digests"))
    expected_envelope = _digest(
        domain=REPORT_ENVELOPE_DIGEST_DOMAIN,
        kind="report_envelope",
        payload=_document_with_envelope_sentinel(document),
    )
    actual_envelope = _digest_value(digests, "envelope")
    if actual_envelope is None or not hmac.compare_digest(
        actual_envelope,
        expected_envelope.value,
    ):
        return "report envelope digest mismatch"
    return None


class _VerificationRefusal(Exception):
    """Internal control flow for the one dispatcher: carries the refusal
    string a verifier utters when the document cannot even name what it
    claims to seal.  Never escapes :func:`verify_report_integrity`."""


def _verification_preamble(
    document: Mapping[str, object],
) -> tuple[Mapping[str, object], str, str]:
    """The shared head of both generations: digests, observation, schema."""

    integrity = _as_mapping(document.get("integrity"))
    digests = _as_mapping(integrity.get("digests"))
    observation_value = _digest_value(digests, "observation")
    if observation_value is None:
        raise _VerificationRefusal("report observation digest is missing")
    report_schema_version = document.get("report_schema_version")
    if not isinstance(report_schema_version, str):
        raise _VerificationRefusal("report schema version is missing")
    return digests, observation_value, report_schema_version


def _finish_verification(
    document: Mapping[str, object],
    digests: Mapping[str, object],
    expected: Mapping[str, ReportDigest],
) -> str | None:
    """The shared tail of both generations: tier mismatch, then envelope."""

    mismatch = _tier_mismatch(digests, expected)
    if mismatch is not None:
        return mismatch
    return _verify_envelope(document)


def _verify_generation_one(document: Mapping[str, object]) -> str | None:
    """Generation-1 rules, preserved verbatim: a document without the
    semantic-identity marker is interpreted in its own generation."""

    digests, observation_value, report_schema_version = _verification_preamble(document)
    source_facts = _as_mapping(document.get("source_facts"))
    baseline = _as_mapping(document.get("baseline"))
    evaluation = _as_mapping(document.get("evaluation"))
    observation = _observation_wire(observation_value)
    analysis_facts = _digest(
        domain=REPORT_ANALYSIS_FACTS_DIGEST_DOMAIN,
        kind="analysis_facts",
        payload={
            "observation_digest": observation,
            "report_schema_version": report_schema_version,
            "source_facts": source_facts,
        },
    )
    comparison = _digest(
        domain=REPORT_COMPARISON_DIGEST_DOMAIN,
        kind="comparison",
        payload={
            "analysis_facts_digest": _digest_wire(analysis_facts),
            "baseline": _comparison_digest_input(baseline),
        },
    )
    evaluation_digest = _digest(
        domain=REPORT_EVALUATION_DIGEST_DOMAIN,
        kind="evaluation",
        payload={
            "comparison_digest": _digest_wire(comparison),
            "evaluation": evaluation,
        },
    )
    return _finish_verification(
        document,
        digests,
        {
            "analysis_facts": analysis_facts,
            "comparison": comparison,
            "evaluation": evaluation_digest,
        },
    )


def _verify_semantic_consistency(
    document: Mapping[str, object],
    semantic: Mapping[str, object],
) -> str | None:
    """The one-fact-spelled-twice checks: every value the semantic block
    copies from the body must agree with the body's own utterance."""

    meta = _as_mapping(document.get("meta"))
    inventory = _as_mapping(document.get("inventory"))
    findings = _as_mapping(document.get("findings"))
    metrics = _as_mapping(document.get("metrics"))
    evaluation = _as_mapping(document.get("evaluation"))
    source_facts = _as_mapping(document.get("source_facts"))
    groups = _as_mapping(findings.get("groups"))
    observation_contract = _as_mapping(source_facts.get("observation_contract"))
    enabled_lanes = frozenset(
        _as_sequence_of_str(observation_contract.get("enabled_lanes"))
    )
    expected_population = _population(
        meta=meta,
        inventory=inventory,
        groups=groups,
        enabled_lanes=enabled_lanes,
    )
    if _as_mapping(semantic.get("population")) != expected_population:
        return "report semantic population does not recompute from the document"
    producers = _as_mapping(expected_population.get("producers"))
    realized = _as_mapping(semantic.get("realized_contracts"))
    for domain_name in ("analysis", "evaluation"):
        for family, entry_raw in sorted(_as_mapping(realized.get(domain_name)).items()):
            entry = _as_mapping(entry_raw)
            params = entry.get("params")
            if params is not None and _params_digest(_as_mapping(params)) != entry.get(
                "params_digest"
            ):
                return (
                    f"report realized contract for {family!r} does not match "
                    "its params digest"
                )
    analysis_realized = _as_mapping(realized.get("analysis"))
    near_miss_entry = _as_mapping(analysis_realized.get("near_miss"))
    if near_miss_entry:
        container = _as_mapping(groups.get("near_miss"))
        revisions = _as_mapping(near_miss_entry.get("algorithm_revisions"))
        if revisions.get("near_miss") != container.get("algorithm_revision"):
            return "report near_miss realized revision disagrees with its container"
        params = _as_mapping(near_miss_entry.get("params"))
        if params.get("max_edit_statements") != container.get("max_edit_statements"):
            return "report near_miss realized budget disagrees with its container"
    expected_comparison = _realized_comparison_contract(meta)
    if _as_mapping(realized.get("comparison")) != expected_comparison:
        return "report realized comparison contract does not recompute from meta"
    gates_entry = _as_mapping(_as_mapping(realized.get("evaluation")).get("gates"))
    contract = _as_mapping(evaluation.get("contract"))
    if gates_entry.get("thresholds_digest") != contract.get("gate_thresholds_digest"):
        return "report realized gate thresholds disagree with the evaluation"
    family_digests = _as_mapping(semantic.get("family_digests"))
    expected_analysis = _analysis_family_digests(groups=groups, producers=producers)
    if _as_mapping(family_digests.get("analysis")) != expected_analysis:
        return "report analysis family digests do not recompute"
    expected_evaluation = _evaluation_family_digests(
        metrics=metrics, producers=producers
    )
    if _as_mapping(family_digests.get("evaluation")) != expected_evaluation:
        return "report evaluation family digests do not recompute"
    return None


def _verify_generation_two(document: Mapping[str, object]) -> str | None:
    digests, observation_value, report_schema_version = _verification_preamble(document)
    integrity = _as_mapping(document.get("integrity"))
    semantic = _as_mapping(integrity.get("semantic"))
    if not semantic:
        return "report semantic identity block is missing"
    consistency = _verify_semantic_consistency(document, semantic)
    if consistency is not None:
        return consistency
    expected = _v2_tier_digests(
        marker=integrity.get("semantic_identity_version"),
        report_schema_version=report_schema_version,
        observation=_observation_wire(observation_value),
        source_facts=_as_mapping(document.get("source_facts")),
        semantic=semantic,
        baseline=_as_mapping(document.get("baseline")),
        evaluation=_as_mapping(document.get("evaluation")),
    )
    return _finish_verification(document, digests, expected)


def verify_report_integrity(document: Mapping[str, object]) -> str | None:
    """Recompute the digest tiers and authenticate the envelope.

    Dispatches on the document's own generation marker: absent means
    generation 1 and generation-1 rules; the current version means
    generation 2; anything else is a typed refusal, never a guess.
    """

    integrity = _as_mapping(document.get("integrity"))
    digests = _as_mapping(integrity.get("digests"))
    required = ("observation", "analysis_facts", "comparison", "evaluation", "envelope")
    if tuple(sorted(digests)) != tuple(sorted(required)):
        return "report digest set must contain exactly five named tiers"
    marker = integrity.get("semantic_identity_version")
    try:
        if marker is None:
            return _verify_generation_one(document)
        if marker == REPORT_SEMANTIC_IDENTITY_VERSION:
            return _verify_generation_two(document)
    except _VerificationRefusal as refusal:
        return str(refusal)
    return (
        f"report semantic identity generation {marker!r} is not verifiable "
        f"by this engine (knows: absent, {REPORT_SEMANTIC_IDENTITY_VERSION!r})"
    )


__all__ = [
    "_build_integrity_payload",
    "build_evaluation_contract",
    "build_evaluation_payload",
    "finalize_envelope_digest",
    "verify_report_integrity",
]
