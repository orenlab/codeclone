# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Closed vocabulary for bounded Platform Observability telemetry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from ..contracts import OBSERVER_VOCABULARY_VERSION

DB_COUNTER_VERSION: Final = 2

# Telemetry planes. An operation either belongs to the product runtime under
# observation or to the observation instrument itself; the two are read through
# separate windows with separate budgets, because a shared window let the
# instrument evict the evidence it had just pointed at. Persisted per operation:
# a row written before this mark existed carries NULL and is reported as
# unattributed, never silently folded into the runtime plane.
PLANE_RUNTIME: Final = "runtime"
PLANE_OBSERVER: Final = "observer"
OBSERVABILITY_PLANES: Final[tuple[str, ...]] = (PLANE_RUNTIME, PLANE_OBSERVER)

# Operations that ARE the instrument. Membership is decided once, at the write
# edge, so the plane is a stored fact rather than a read-time guess that every
# consumer would have to re-derive identically.
OBSERVER_PLANE_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "mcp.query_platform_observability",
    }
)


def resolve_operation_plane(operation_name: str) -> str:
    """Return the plane an operation belongs to, from its name."""
    return (
        PLANE_OBSERVER if operation_name in OBSERVER_PLANE_OPERATIONS else PLANE_RUNTIME
    )


# One entry per MCP tool a caller can reach, over BOTH governance channels
# (get_workspace_session_stats and get_controller_audit_trail are registered
# only when ide_governance_channel is on, so the default registry is not the
# whole registry). server.py wraps every tool call in
# span(name=f"mcp.{tool_name}") and validate_span_name is unconditional, so a
# tool missing from this set does not lose telemetry — it stops executing, and
# the caller gets an ObservabilityVocabularyError instead of an answer. This is
# a copy of a set that lives elsewhere, kept because codeclone.observability is
# ring r1 and cannot import the r4 server (nor the optional mcp runtime it
# needs); tests/test_observability_vocabulary.py therefore compares it to the
# live registry in both directions rather than to a second hand-written list.
_MCP_TOOL_NAMES: Final = frozenset(
    {
        "analyze_changed_paths",
        "analyze_repository",
        "check_authority",
        "check_clones",
        "check_cohesion",
        "check_complexity",
        "check_coupling",
        "check_dead_code",
        "check_patch_contract",
        "clear_session_runs",
        "compare_runs",
        "create_review_receipt",
        "evaluate_gates",
        "finish_controlled_change",
        "generate_pr_summary",
        "get_blast_artifact",
        "get_blast_radius",
        "get_controller_audit_trail",
        "get_finding",
        "get_implementation_context",
        "get_implementation_context_page",
        "get_memory_projection_page",
        "get_patch_trail",
        "get_production_triage",
        "get_relevant_memory",
        "get_remediation",
        "get_report_section",
        "get_review_receipt",
        "get_run_summary",
        "get_workspace_session_stats",
        "help",
        "list_findings",
        "list_hotspots",
        "list_reviewed_findings",
        "manage_change_intent",
        "manage_engineering_memory",
        "mark_finding_reviewed",
        "query_engineering_memory",
        "query_platform_observability",
        "start_controlled_change",
        "validate_review_claims",
    }
)

SPAN_NAMES: Final[frozenset[str]] = frozenset(
    {
        "analytics.build",
        "analytics.cluster",
        "analytics.embed",
        "analytics.report",
        "analytics.snapshot",
        "analysis.registry_bind",
        "analysis.relative_imports",
        "audit.digest_link",
        "baseline.container.build",
        "baseline.container.publish",
        "baseline.container.read",
        "baseline.container.trust",
        "cache.backend.activate_generation",
        "cache.backend.load_generation",
        "cache.backend.prune",
        "cache.backend.write_generation",
        "cache.content_identity",
        "cache.decode_entries",
        "cache.profile_reuse",
        "cache.release_entries",
        "cache.segment_projection",
        "cache.stat",
        "cache.validate_envelope",
        "canonical.snapshot.publish",
        "canonical.store.publish",
        "compatibility.check",
        "config.resolve",
        "controller.registry_bind",
        "gc.collect",
        "gc.run",
        "hygiene.collect_dirty_paths",
        "hygiene.collect_dirty_snapshot",
        "hygiene.dirty_entry_digests",
        "hygiene.git.rev_parse",
        "hygiene.git.status",
        "manifest.build",
        "memory.embedding.documents",
        "memory.embedding.infer",
        "memory.embedding.model_load",
        "memory.embedding.query",
        "memory.experience.distill",
        "memory.identity.migrate",
        "memory.retrieval.merge",
        "memory.semantic.bootstrap",
        "memory.semantic.embed",
        "memory.semantic.rebuild",
        "memory.semantic.reconcile",
        "memory.semantic.search",
        "memory.semantic.source.audit",
        "memory.semantic.source.memory",
        "memory.semantic.source.trajectory",
        "memory.subject.resolve",
        "memory.trajectory.rebuild",
        "memory.projection.worker_bootstrap",
        "observations.build",
        "observations.lanes.build",
        "pipeline.analyze",
        "pipeline.baseline",
        "pipeline.bootstrap",
        "pipeline.cache_load",
        "pipeline.discover",
        "pipeline.process",
        "pipeline.report",
        "registry.build",
        "release.phase39.matrix",
        "report.build",
        "report.evaluate",
        "report.finalize",
        "report.html.context",
        "report.html.sections",
        "report.html.styles",
        "report.render",
        "retrieval.embed_query",
        "semantics.authority.build",
        "semantics.events",
        "semantics.flow",
        "mcp.run_store.register",
        "mcp.run_store.resolve_artifact",
        *(f"mcp.{name}" for name in _MCP_TOOL_NAMES),
    }
)

COUNTER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "audit.emit_dropped",
        "batch",
        "batches",
        "cache_entries",
        "cache_file_bytes",
        "cache_hits",
        "chars",
        "count",
        "db_queries",
        "db_rows",
        "db_writes",
        "decoded_entries",
        "deleted",
        "dirty_entries",
        "dirty_paths",
        "documents",
        "embedded",
        "embedding_batch_size",
        "embedding_dimensions",
        "embedding_max_padded_tokens",
        "experiences_distilled",
        "failed_files",
        "files_analyzed",
        "files_to_process",
        "git_diff_invocations",
        "html_css_chars",
        "html_js_chars",
        "html_section_chars",
        "html_sections_rendered",
        "indexed",
        "lane_audit",
        "lane_memory",
        "lane_trajectory",
        "max_chars",
        "max_documents",
        "max_padded_tokens",
        "max_tokens",
        "memory.propose_candidate_dropped",
        "padded_tokens",
        "padding_amplification_permille",
        "pending",
        "phase_class_metrics_us",
        "phase_dead_code_us",
        "phase_module_bindings_us",
        "phase_module_passes_us",
        "phase_module_walk_us",
        "phase_parse_us",
        "phase_qualname_us",
        "phase_relationship_us",
        "phase_suppressions_us",
        "phase_unit_blocks_us",
        "phase_unit_cfg_us",
        "phase_unit_normalize_cfg_us",
        "phase_unit_normalize_stmt_us",
        "phase_unit_segments_us",
        "phase_unit_structural_us",
        "released_entries",
        "retrieval.fts_hits",
        "retrieval.fts_vector_overlap",
        "retrieval.semantic_filtered",
        "retrieval.vector_audit_hits",
        "retrieval.vector_memory_hits",
        "retrieval.vector_trajectory_hits",
        "skipped_unchanged",
        "spans_dropped",
        "subphase_module_passes_adoption_us",
        "subphase_module_passes_reachability_binding_us",
        "subphase_module_passes_reachability_visit_us",
        "subphase_module_passes_security_us",
        "total_chars",
        "total_tokens",
        "untracked_file_reads",
        "workflows_seen",
        # Phase 39 aggregate vocabulary. Enum-valued outcomes are represented
        # as one fixed key per closed value by their owning slice.
        "analysis_dependency_targets",
        "analysis_inventory_submodule_expansions",
        "analysis_known_internal_not_analyzed",
        "candidates_emitted",
        "cache_backend_changed_entries",
        "cache_backend_contention",
        "cache_backend_entries",
        "cache_backend_orphans",
        "cache_backend_pruned",
        "cache_backend_read_bytes",
        "cache_backend_recovery_corrupt",
        "cache_backend_recovery_current",
        "cache_backend_recovery_previous",
        "cache_backend_removed_entries",
        "cache_backend_write_bytes",
        "cache_content_decision_blob_hit",
        "cache_content_decision_digest_hit",
        "cache_content_decision_digest_miss",
        "cache_content_decision_dirty",
        "cache_content_decision_git_unavailable",
        "cache_content_decision_index_ambiguous",
        "cache_content_decision_racy",
        "cache_content_decision_untracked",
        "cache_content_digest_verify_cost_us",
        "cache_lane_dependent_miss",
        "cache_lane_neutral_hit",
        "cache_profile_hit",
        "cache_profile_miss",
        "cache_stat_fast_reject",
        # The producer edge of the canonical backend (step 7): ONE span at
        # the ONE publication point, deliberately NOT in the
        # ``canonical_store_*`` family — that family has exactly one owner
        # (the store), and a witness emitted from core under its name would
        # make it a second instrumentation surface.  This is the rollout's
        # own line, and it exists because the DEFAULT path here is the
        # skip: a publication that skipped silently would look exactly like
        # a backend nobody wired.
        #
        #  run_snapshot_publish_attempts       one call, always written.
        #  *_disabled / *_refused / *_stored   EXCLUSIVE outcomes; exactly
        #      one is written per call, so "nothing happened" is always
        #      distinguishable from "the site was never reached".
        #  *_inadmissible                      0/1, written on every stored
        #      publish: whether this realized profile was refused the
        #      canonical head (partial / clones-only / truncated).
        "run_snapshot_publish_attempts",
        "run_snapshot_publish_disabled",
        "run_snapshot_publish_inadmissible",
        "run_snapshot_publish_refused",
        "run_snapshot_publish_stored",
        # The canonical backend run-store, instrumented before its rollout
        # flag and before any sweep exists: without this the backend's own
        # first operational line — first publish, republish, content
        # sharing, database growth, head contention — would have to be
        # reconstructed afterwards from an experiment nobody can repeat.
        # Deliberately NOT a second telemetry surface: one span name inside
        # the one observation point, and no name is minted for a mechanism
        # this build does not execute (there is no GC family here, because
        # there is no sweep to emit it).
        #
        # Magnitudes are always written, zero included — an absent magnitude
        # cannot be told apart from a span that never reached the site.
        # Outcomes are exclusive and only the one that fired is written.
        #
        #  *_attempts / *_successes / *_failures  one publish call; a stale
        #      publisher is NOT a failure, it stored a valid immutable run
        #      and lost only the head race.
        #  *_ingest_duration   whole microseconds of the staging phase
        #      (normalize, row encode, content addresses, run identity).
        #  *_write_duration    whole microseconds of the fenced transaction,
        #      measured from before BEGIN IMMEDIATE — where a second
        #      publisher waits, so contention lands here and nowhere else.
        #  *_new_objects / *_reused_objects   the content-sharing split of
        #      one run's objects.
        #  *_membership_rows   membership rows this publish actually wrote:
        #      the per-run cost that content sharing does NOT save, and zero
        #      for a republish of a run the store already holds.
        #  *_db_bytes          page_count * page_size after the commit, not
        #      the file size, which lags a WAL commit until a checkpoint.
        #  *_head_advance_*    compare-and-swap outcome of the target head.
        "canonical_store_db_bytes",
        "canonical_store_head_advance_conflicts",
        "canonical_store_head_advance_successes",
        "canonical_store_ingest_duration",
        "canonical_store_membership_rows",
        "canonical_store_new_objects",
        "canonical_store_publish_attempts",
        "canonical_store_publish_failures",
        "canonical_store_publish_successes",
        "canonical_store_reused_objects",
        "canonical_store_write_duration",
        "compatibility_status_compatible",
        "compatibility_status_incompatible",
        "compatibility_status_migration_required",
        "compatibility_status_unknown_contract",
        "config_autodetect_used",
        "config_configured_roots",
        "config_validation_failures",
        "contract_count",
        "controller_registry_bindings",
        "events_by_kind.artifact_write",
        "events_by_kind.assign",
        "events_by_kind.compatibility_check",
        "events_by_kind.compute_digest",
        "events_by_kind.construct",
        "events_by_kind.field_write",
        "events_by_kind.publish_event",
        "events_by_kind.resolve_identity",
        "events_by_kind.return_value",
        "events_by_kind.serialize_field",
        "events_by_kind.security_observation",
        "events_unresolved",
        "facts_bound",
        # The unified GC orchestrator (codeclone.api.gc) is the ONE
        # emitter of this family: jobs answer through the protocol and the
        # orchestrator turns the answer into the observation, so three
        # collecting surfaces cannot mint three dialects about one event.
        # Every reason is written on every job span, zero included — an
        # absent magnitude cannot be told apart from a span that never
        # reached the site.
        #
        #  gc_jobs_*        one orchestration on the gc.run span: how many
        #      jobs were dispatched, answered with a collection, or
        #      answered with a typed refusal.  A refusal is a visible
        #      event, never silence — silence is indistinguishable from
        #      "nothing to collect".
        #  gc_candidates    objects one job examined, on its gc.collect
        #      span (the span's reason names the job).
        #  gc_held_*        the DECISION lane: which root/predicate held
        #      the uncollected candidates (head, retained history window,
        #      live lease, explicit retention, in-flight staging, live
        #      owner), so "why was this not collected" is answerable
        #      without reading code.
        #  gc_collected_*   the verdict lane: what left the surface's live
        #      universe and under which closed reason (deadline expired,
        #      owner dead, unreachable from every root, corrupt row).
        #  gc_job_refused   0/1 on the job's own span.
        "gc_candidates",
        "gc_collected_corrupt",
        "gc_collected_expired",
        "gc_collected_orphaned",
        "gc_collected_unreachable",
        "gc_held_head",
        "gc_held_history",
        "gc_held_lease",
        "gc_held_owner_alive",
        "gc_held_retained",
        "gc_held_staging",
        "gc_job_refused",
        "gc_jobs_collected",
        "gc_jobs_dispatched",
        "gc_jobs_refused",
        "manifest_collisions",
        "manifest_input_files",
        "manifest_mounts",
        "manifest_null_modules",
        "manifest_portability_failures",
        "manifest_resolved_modules",
        "memory_fts_candidates",
        "memory_invalidated_jobs",
        "memory_jobs_coalesced",
        "memory_migration_failed",
        "memory_migration_migrated",
        "memory_migration_noop",
        "memory_subjects_mapped",
        "memory_subjects_unchanged",
        "memory_subjects_unresolved",
        "memory_unique_record_ids",
        "memory_vector_candidates",
        "memory_vector_fts_overlap",
        "observations_contract_failures",
        "observations_enabled_lanes",
        "observations_fact_families",
        "observations_lane_bytes",
        "observations_lane_items",
        "observations_semantic_reuse",
        "registry_analyzed",
        "registry_collisions",
        "registry_discovered",
        "registry_hard_excluded",
        "registry_inventoried",
        "registry_known_internal_not_analyzed",
        "registry_null_modules",
        "registry_worker_installs",
        "release_bytes",
        "release_duration_ms",
        "release_failed",
        "release_passed",
        "release_rss_mb",
        "release_scenarios",
        "release_sql_statements",
        "report_gate_fail",
        "report_gate_pass",
        "report_items",
        "report_novelty_known",
        "report_novelty_new",
        "report_novelty_unavailable",
        "report_render_bytes",
        "report_render_format_html",
        "report_render_format_json",
        "report_render_format_markdown",
        "report_render_format_sarif",
        "report_render_format_text",
        "report_trust_trusted",
        "report_trust_untrusted",
        "run_store_artifact_bytes",
        "run_store_artifacts_drifted",
        "run_store_artifacts_missing",
        "run_store_artifacts_retained",
        "run_store_evaluations_evicted",
        "run_store_evaluations_retained",
        "run_store_expired",
        "run_store_runs_evicted",
        "run_store_runs_retained",
        "run_store_selector_hits",
        "run_store_selector_misses",
        "audit_digest_links",
        "baseline_bytes",
        "baseline_compatibility_fail",
        "baseline_compatibility_pass",
        "baseline_items",
        "baseline_lanes",
        "baseline_publish_backups",
        "baseline_publish_bytes",
        "baseline_publish_conflict",
        "baseline_publish_failure",
        "baseline_publish_fsyncs",
        "baseline_publish_lanes",
        "baseline_publish_noop",
        "baseline_publish_recovered",
        "baseline_publish_replaced",
        "baseline_publish_transitions",
        "baseline_root_verification_fail",
        "baseline_root_verification_pass",
        "baseline_lane_verification_fail",
        "baseline_lane_verification_pass",
        "baseline_read_failures",
        "files_timed",
        "files_discovered",
        "files_inventoried",
        "fixpoint_iterations",
        "functions_summarized",
        "ir_nodes",
        "scc_count",
        "sinks_by_status.adapter",
        "sinks_by_status.authoritative",
        "sinks_by_status.mixed",
        "sinks_by_status.shadow",
        "sinks_by_status.unavailable",
        "typed_failures",
        "units_eligible",
        "units_fingerprinted",
        "units_seen",
        "unresolved_flow_functions",
        "unresolved_relatives",
        "blocks_emitted",
        "segments_emitted",
    }
)


# --------------------------------------------------------------------------
# Parking
#
# A declared name with no emit site is not "instrumented" — it is a claim the
# build cannot honour, and the reverse-direction test in
# tests/test_observability_vocabulary.py fails on any such name. Removing the
# name instead would be an OBSERVER_VOCABULARY_VERSION change, so a name that
# genuinely cannot be wired in this build is parked here with the reason it
# cannot be, and parking is the only way past that test. A parked name that
# later acquires an emit site must be removed from this registry — the test
# fails on a name that is both parked and emitted, so parking can never quietly
# outlive the reason for it.
PARK_DEFERRED_PHASE_39K: Final = "deferred_phase_39k"
PARK_OUT_OF_PACKAGE_HARNESS: Final = "out_of_package_harness"
PARK_RING_BOUNDARY: Final = "ring_boundary"
PARK_SUPERSEDED: Final = "superseded"
PARK_SUBSYSTEM_ABSENT: Final = "subsystem_absent"

PARK_REASONS: Final[Mapping[str, str]] = {
    PARK_DEFERRED_PHASE_39K: (
        "reserved for the Phase 39K cache backend; that backend now exists and "
        "the names it emits have left this list, but the ones still here name "
        "a generation-recovery and contention design it does not implement, so "
        "no code path produces them"
    ),
    PARK_OUT_OF_PACKAGE_HARNESS: (
        "emitted by a release harness that lives outside the shipped package"
    ),
    PARK_RING_BOUNDARY: (
        "the only module that could emit it sits in a lower architecture ring "
        "than codeclone.observability and cannot import it"
    ),
    PARK_SUPERSEDED: "a live name already records this fact",
    PARK_SUBSYSTEM_ABSENT: "no code path in this build produces the fact",
}

PARKED_SPAN_NAMES: Final[Mapping[str, str]] = {
    "audit.digest_link": PARK_SUBSYSTEM_ABSENT,
    # codeclone.contracts is ring r0; codeclone.observability is r1.
    "compatibility.check": PARK_RING_BOUNDARY,
    "controller.registry_bind": PARK_SUPERSEDED,  # analysis.registry_bind
    "memory.identity.migrate": PARK_SUBSYSTEM_ABSENT,
    "memory.retrieval.merge": PARK_SUPERSEDED,  # memory.semantic.search
    "memory.subject.resolve": PARK_SUBSYSTEM_ABSENT,
    "release.phase39.matrix": PARK_OUT_OF_PACKAGE_HARNESS,
}

PARKED_COUNTER_KEYS: Final[Mapping[str, str]] = {
    "audit_digest_links": PARK_SUBSYSTEM_ABSENT,
    "baseline_publish_recovered": PARK_SUBSYSTEM_ABSENT,
    "cache_backend_contention": PARK_DEFERRED_PHASE_39K,
    "cache_backend_recovery_corrupt": PARK_DEFERRED_PHASE_39K,
    "cache_backend_recovery_current": PARK_DEFERRED_PHASE_39K,
    "cache_backend_recovery_previous": PARK_DEFERRED_PHASE_39K,
    "compatibility_status_compatible": PARK_RING_BOUNDARY,
    "compatibility_status_incompatible": PARK_RING_BOUNDARY,
    "compatibility_status_migration_required": PARK_RING_BOUNDARY,
    "compatibility_status_unknown_contract": PARK_RING_BOUNDARY,
    "contract_count": PARK_RING_BOUNDARY,
    "controller_registry_bindings": PARK_SUPERSEDED,  # registry_* on registry.build
    "files_discovered": PARK_SUPERSEDED,  # registry_discovered
    "files_inventoried": PARK_SUPERSEDED,  # registry_inventoried
    "memory_fts_candidates": PARK_SUPERSEDED,  # retrieval.fts_hits
    "memory_invalidated_jobs": PARK_SUBSYSTEM_ABSENT,
    "memory_jobs_coalesced": PARK_SUBSYSTEM_ABSENT,
    "memory_migration_failed": PARK_SUBSYSTEM_ABSENT,
    "memory_migration_migrated": PARK_SUBSYSTEM_ABSENT,
    "memory_migration_noop": PARK_SUBSYSTEM_ABSENT,
    "memory_subjects_mapped": PARK_SUBSYSTEM_ABSENT,
    "memory_subjects_unchanged": PARK_SUBSYSTEM_ABSENT,
    "memory_subjects_unresolved": PARK_SUBSYSTEM_ABSENT,
    "memory_unique_record_ids": PARK_SUBSYSTEM_ABSENT,
    "memory_vector_candidates": PARK_SUPERSEDED,  # retrieval.vector_memory_hits
    "memory_vector_fts_overlap": PARK_SUPERSEDED,  # retrieval.fts_vector_overlap
    "release_bytes": PARK_OUT_OF_PACKAGE_HARNESS,
    "release_duration_ms": PARK_OUT_OF_PACKAGE_HARNESS,
    "release_failed": PARK_OUT_OF_PACKAGE_HARNESS,
    "release_passed": PARK_OUT_OF_PACKAGE_HARNESS,
    "release_rss_mb": PARK_OUT_OF_PACKAGE_HARNESS,
    "release_scenarios": PARK_OUT_OF_PACKAGE_HARNESS,
    "release_sql_statements": PARK_OUT_OF_PACKAGE_HARNESS,
    # The session run store holds runs and pins. It has no evaluation cache and
    # no time-to-live, so nothing can evict, retain or expire an evaluation.
    "run_store_evaluations_evicted": PARK_SUBSYSTEM_ABSENT,
    "run_store_evaluations_retained": PARK_SUBSYSTEM_ABSENT,
    "run_store_expired": PARK_SUBSYSTEM_ABSENT,
}


class ObservabilityVocabularyError(ValueError):
    """A span name or counter key is outside the reviewed vocabulary."""


def validate_span_name(name: str) -> str:
    if name not in SPAN_NAMES:
        raise ObservabilityVocabularyError(
            f"unknown observability span name {name!r}; update the reviewed vocabulary"
        )
    return name


def validate_counter_key(key: str) -> str:
    if key not in COUNTER_KEYS:
        raise ObservabilityVocabularyError(
            f"unknown observability counter key {key!r}; update the reviewed vocabulary"
        )
    return key


__all__ = [
    "COUNTER_KEYS",
    "DB_COUNTER_VERSION",
    "OBSERVABILITY_PLANES",
    "OBSERVER_PLANE_OPERATIONS",
    "OBSERVER_VOCABULARY_VERSION",
    "PARKED_COUNTER_KEYS",
    "PARKED_SPAN_NAMES",
    "PARK_DEFERRED_PHASE_39K",
    "PARK_OUT_OF_PACKAGE_HARNESS",
    "PARK_REASONS",
    "PARK_RING_BOUNDARY",
    "PARK_SUBSYSTEM_ABSENT",
    "PARK_SUPERSEDED",
    "PLANE_OBSERVER",
    "PLANE_RUNTIME",
    "SPAN_NAMES",
    "ObservabilityVocabularyError",
    "resolve_operation_plane",
    "validate_counter_key",
    "validate_span_name",
]
