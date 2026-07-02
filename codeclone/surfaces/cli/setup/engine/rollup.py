# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Readiness derivation (R1-R9) and maturity rollup.

``derive_readiness`` is the single authority for the ``readiness`` axis: it is a
pure function of capability metadata plus the detected axes. Presentation only
supplies human ``reason``/``recommended_action`` copy for the already-derived
readiness and must never change it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from .....analytics.capabilities import check_capability, install_hint
from .....baseline import BaselineStatus
from .....paths.gitignore import gitignore_codeclone_cache_tip_payload
from .....ui_messages import setup as setup_ui
from .capabilities import (
    CapabilityAxes,
    CapabilityMeta,
    DiscoverContext,
    ProbedCapability,
)

Readiness = Literal["ready", "attention", "blocked", "optional", "not_applicable"]
Guidance = tuple[str, str]
GuidanceHandler = Callable[
    [CapabilityMeta, CapabilityAxes, Readiness, DiscoverContext],
    Guidance,
]

_UNVERIFIED_RUNTIME: frozenset[str] = frozenset({"unavailable", "not_verified"})
_CI_FLAGS: tuple[str, ...] = ("ci", "fail_on_new", "fail_on_new_metrics")


def finalize_capabilities(
    probed: list[ProbedCapability],
    ctx: DiscoverContext,
) -> list[dict[str, object]]:
    finalized: list[dict[str, object]] = []
    for item in probed:
        readiness = derive_readiness(item.meta, item.axes)
        reason, action = describe_capability(item.meta, item.axes, readiness, ctx)
        finalized.append(
            {
                "id": item.meta.id,
                "label": setup_ui.CAPABILITY_LABELS[item.meta.id],
                "group": item.meta.group,
                "availability": item.meta.availability,
                "installation": item.axes.installation,
                "configuration": item.axes.configuration,
                "runtime": item.axes.runtime,
                "readiness": readiness,
                "reason": reason,
                "evidence": list(item.axes.evidence),
                "recommended_action": action,
            }
        )
    return finalized


def compute_maturity(
    capabilities: dict[str, dict[str, object]],
    *,
    memory_db_exists: bool,
) -> dict[str, bool]:
    def readiness(cap_id: str) -> str:
        return str(capabilities[cap_id]["readiness"])

    return {
        "connected": readiness("analysis") != "blocked",
        "governed": readiness("controlled_change") in {"ready", "optional"}
        and readiness("audit_and_intents") != "blocked",
        "evidence_backed": readiness("engineering_memory") in {"ready", "attention"}
        and memory_db_exists,
        "team_ready": all(
            readiness(cap_id) != "blocked"
            for cap_id in (
                "github_workflow",
                "pre_commit_hook",
                "workspace_hygiene",
            )
        ),
        "release_ready": readiness("baseline") == "ready"
        and readiness("ci_policy") in {"ready", "attention"},
    }


# ---------------------------------------------------------------------------
# Readiness authority (§10.4.3 decision table, first match wins)
# ---------------------------------------------------------------------------


def derive_readiness(meta: CapabilityMeta, axes: CapabilityAxes) -> Readiness:
    # R1
    if meta.availability == "unsupported":
        return "not_applicable"
    # R2 — optional extra not installed is optional, never blocked (I-02).
    if meta.availability == "optional_extra" and axes.installation == "missing":
        return "optional"
    # R2a — installed optional extra with bad config is attention, never blocked.
    if (
        meta.availability == "optional_extra"
        and axes.installation != "missing"
        and axes.configuration == "invalid"
    ):
        return "attention"
    # R3 — optional extra with an ambiguous install probe (fail closed).
    if meta.availability == "optional_extra" and axes.installation == "unknown":
        return "attention"
    # R4 — non-optional capability with an ambiguous install probe (fail closed).
    if axes.installation == "unknown" and meta.availability != "optional_extra":
        return "attention"
    # R5 — required capability with invalid config is blocked.
    if axes.configuration == "invalid" and meta.availability in {
        "built_in",
        "external_tool",
    }:
        return "blocked"
    # R6 — capability that needs config but is unconfigured.
    if axes.configuration == "unconfigured" and meta.requires_config:
        return "attention"
    # R7 — capability that needs runtime proof but is not verified.
    if meta.requires_runtime_proof and axes.runtime in _UNVERIFIED_RUNTIME:
        return "attention"
    # R8 — every axis satisfied.
    if _axes_satisfied(meta, axes):
        return "ready"
    # R9 — conservative default.
    return "attention"


def _axes_satisfied(meta: CapabilityMeta, axes: CapabilityAxes) -> bool:
    if axes.installation == "unknown":
        return False
    if axes.configuration == "invalid":
        return False
    if meta.requires_config and axes.configuration == "unconfigured":
        return False
    return not (meta.requires_runtime_proof and axes.runtime in _UNVERIFIED_RUNTIME)


# ---------------------------------------------------------------------------
# Presentation: reason + recommended_action for an already-derived readiness.
# Handlers never return a different readiness.
# ---------------------------------------------------------------------------


def describe_capability(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    handler = _GUIDANCE_BY_ID.get(meta.id, _describe_generic)
    return handler(meta, axes, readiness, ctx)


def _describe_generic(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del ctx
    if readiness == "ready":
        return ("", "")
    if readiness == "optional":
        return (setup_ui.REASON_OPTIONAL_EXTRA_MISSING, _optional_install_hint(meta))
    if readiness == "not_applicable":
        return (setup_ui.REASON_NOT_APPLICABLE, "")
    if axes.installation == "unknown":
        return (setup_ui.REASON_UNKNOWN_PROBE, "")
    return (setup_ui.REASON_ATTENTION_GENERIC, "")


def _describe_analysis(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta, readiness, ctx
    if axes.installation == "unknown":
        return (setup_ui.REASON_ANALYSIS_CORE_MISSING, "")
    if axes.configuration == "invalid":
        return (setup_ui.REASON_ANALYSIS_INVALID_CONFIG, setup_ui.ACTION_FIX_PYPROJECT)
    if axes.configuration == "unconfigured":
        return (
            setup_ui.REASON_ANALYSIS_UNCONFIGURED,
            "Add a [tool.codeclone] section to pyproject.toml.",
        )
    return ("", "")


def _describe_baseline(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta, readiness
    name = ctx.baseline_path.name
    if axes.installation == "unknown":
        return (
            setup_ui.REASON_BASELINE_UNREADABLE,
            f"Check permissions on {name}.",
        )
    status = ctx.baseline_status
    if status is BaselineStatus.OK:
        return ("", "")
    if status is not None and status.name != "MISSING":
        if _baseline_corrupt(status):
            return (
                setup_ui.REASON_BASELINE_CORRUPT,
                f"Regenerate the baseline at {name}.",
            )
        return (
            setup_ui.REASON_BASELINE_UNTRUSTED,
            f"Regenerate or repair the baseline at {name}.",
        )
    return (
        setup_ui.REASON_BASELINE_MISSING,
        f"Create a trusted baseline at {name}.",
    )


def _describe_mcp_runtime(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta, readiness, ctx
    if axes.installation == "missing":
        return (setup_ui.REASON_REQUIRES_MCP_EXTRA, setup_ui.MCP_INSTALL_HINT)
    return (
        setup_ui.REASON_MCP_INSTALLED_NOT_VERIFIED,
        setup_ui.MCP_CONFIGURE_CLIENT_HINT,
    )


def _describe_controlled_change(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta, ctx
    if axes.installation == "missing":
        return (setup_ui.REASON_REQUIRES_MCP_EXTRA, setup_ui.MCP_UV_INSTALL_HINT)
    if readiness == "ready":
        return ("", "")
    return (
        setup_ui.REASON_CONTROLLED_CHANGE_NO_CLIENT,
        setup_ui.MCP_CONFIGURE_CLIENT_HINT,
    )


def _describe_audit(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta
    if axes.configuration == "invalid":
        return (setup_ui.REASON_ANALYSIS_INVALID_CONFIG, setup_ui.ACTION_FIX_PYPROJECT)
    if not ctx.audit_enabled:
        return (
            setup_ui.REASON_AUDIT_DISABLED,
            "Set audit_enabled = true under [tool.codeclone] to record controller "
            "events.",
        )
    if not ctx.audit_db_exists:
        return (
            setup_ui.REASON_AUDIT_DB_MISSING,
            "Run a governed MCP workflow to create the audit database.",
        )
    if readiness == "ready":
        return (setup_ui.REASON_AUDIT_READY, "")
    return (
        setup_ui.REASON_AUDIT_EMPTY,
        "Run a governed MCP change to record the first audit event.",
    )


def _describe_engineering_memory(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta
    if axes.configuration == "invalid":
        return (setup_ui.REASON_ANALYSIS_INVALID_CONFIG, setup_ui.ACTION_FIX_PYPROJECT)
    if readiness == "ready":
        return ("", "")
    report = ctx.memory_report
    if report is not None and report.db_exists:
        return (
            setup_ui.REASON_MEMORY_EMPTY,
            "Record engineering memory via governed MCP changes to populate the store.",
        )
    return (
        setup_ui.REASON_MEMORY_MISSING,
        "Run codeclone memory init after analysis to create the store.",
    )


def _describe_semantic_retrieval(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta
    if axes.installation == "missing":
        return (setup_ui.REASON_SEMANTIC_OPTIONAL, "uv sync --extra semantic-local")
    if readiness == "ready":
        return ("", "")
    report = ctx.memory_report
    if report is None or not report.db_exists:
        return (
            setup_ui.REASON_SEMANTIC_NO_STORE,
            "Initialize a memory store, then enable semantic retrieval.",
        )
    return (
        setup_ui.REASON_SEMANTIC_DISABLED,
        "Enable semantic memory under [tool.codeclone.memory].",
    )


def _describe_coverage_evidence(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta, readiness, ctx
    if axes.installation == "missing":
        return (setup_ui.REASON_COVERAGE_OPTIONAL, "uv sync --extra coverage-xml")
    return ("", "")


def _describe_analytics_cockpit(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta, readiness, ctx
    if axes.installation == "missing":
        status = check_capability("full")
        return (
            setup_ui.REASON_ANALYTICS_OPTIONAL,
            install_hint(status.missing_packages),
        )
    return ("", "")


def _describe_ci_policy(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta
    if axes.configuration == "invalid":
        return (setup_ui.REASON_ANALYSIS_INVALID_CONFIG, setup_ui.ACTION_FIX_PYPROJECT)
    if readiness == "ready":
        return ("", "")
    if not _ci_flags_set(ctx):
        return (
            setup_ui.REASON_CI_NOT_ENABLED,
            "Enable ci / fail_on_new under [tool.codeclone] to gate changes in CI.",
        )
    return (
        setup_ui.REASON_CI_BASELINE_ATTENTION,
        "Ensure baseline trust before enabling CI gates.",
    )


def _describe_external_file(
    axes: CapabilityAxes,
    readiness: Readiness,
    *,
    unreadable_reason: str,
    missing_reason: str,
    missing_action: str,
) -> Guidance:
    """Shared guidance for external-tool capabilities detected via a repo file."""

    if axes.installation == "unknown":
        return (unreadable_reason, "")
    if readiness == "ready":
        return ("", "")
    return (missing_reason, missing_action)


def _describe_github_workflow(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta, ctx
    return _describe_external_file(
        axes,
        readiness,
        unreadable_reason=setup_ui.REASON_GITHUB_WORKFLOW_UNREADABLE,
        missing_reason=setup_ui.REASON_GITHUB_WORKFLOW_MISSING,
        missing_action="Add a GitHub Actions workflow that runs codeclone in CI.",
    )


def _describe_pre_commit_hook(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta, ctx
    return _describe_external_file(
        axes,
        readiness,
        unreadable_reason=setup_ui.REASON_PRE_COMMIT_UNREADABLE,
        missing_reason=setup_ui.REASON_PRE_COMMIT_MISSING,
        missing_action="Add a pre-commit hook entry for codeclone.",
    )


def _describe_workspace_hygiene(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> Guidance:
    del meta, axes, ctx
    if readiness == "ready":
        return ("", "")
    tip = gitignore_codeclone_cache_tip_payload()
    return (setup_ui.REASON_WORKSPACE_HYGIENE, str(tip.get("message", "")))


_GUIDANCE_BY_ID: dict[str, GuidanceHandler] = {
    "analysis": _describe_analysis,
    "analytics_cockpit": _describe_analytics_cockpit,
    "audit_and_intents": _describe_audit,
    "baseline": _describe_baseline,
    "ci_policy": _describe_ci_policy,
    "controlled_change": _describe_controlled_change,
    "coverage_evidence": _describe_coverage_evidence,
    "engineering_memory": _describe_engineering_memory,
    "github_workflow": _describe_github_workflow,
    "mcp_runtime": _describe_mcp_runtime,
    "pre_commit_hook": _describe_pre_commit_hook,
    "semantic_retrieval": _describe_semantic_retrieval,
    "workspace_hygiene": _describe_workspace_hygiene,
}


def _optional_install_hint(meta: CapabilityMeta) -> str:
    if meta.optional_extra_name == "mcp":
        return setup_ui.MCP_INSTALL_HINT
    if meta.optional_extra_name == "analytics":
        return install_hint(check_capability("full").missing_packages)
    if meta.optional_extra_name == "coverage-xml":
        return "uv sync --extra coverage-xml"
    if meta.optional_extra_name == "semantic-local":
        return "uv sync --extra semantic-local"
    return ""


def _baseline_corrupt(status: BaselineStatus) -> bool:
    name = status.name
    return name == "INVALID_JSON" or "SCHEMA" in name or "CORRUPT" in name


def _ci_flags_set(ctx: DiscoverContext) -> bool:
    return any(bool(ctx.config.get(flag)) for flag in _CI_FLAGS)


__all__ = [
    "compute_maturity",
    "derive_readiness",
    "describe_capability",
    "finalize_capabilities",
]
