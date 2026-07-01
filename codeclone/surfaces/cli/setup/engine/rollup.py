# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Readiness derivation (R1-R9) and maturity rollup."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from .....analytics.capabilities import check_capability, install_hint
from .....paths.gitignore import gitignore_codeclone_cache_tip_payload
from .....ui_messages import setup as setup_ui
from .capabilities import (
    CapabilityAxes,
    CapabilityMeta,
    DiscoverContext,
    ProbedCapability,
)

Readiness = Literal["ready", "attention", "blocked", "optional", "not_applicable"]
PresentationResult = tuple[Readiness, str, str]
PresentationHandler = Callable[
    [CapabilityMeta, CapabilityAxes, Readiness, DiscoverContext],
    PresentationResult,
]


def finalize_capabilities(
    probed: list[ProbedCapability],
    ctx: DiscoverContext,
) -> list[dict[str, object]]:
    finalized: list[dict[str, object]] = []
    for item in probed:
        readiness = derive_readiness(item.meta, item.axes)
        readiness, reason, action = apply_capability_presentation(
            item.meta,
            item.axes,
            readiness,
            ctx,
        )
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


def derive_readiness(meta: CapabilityMeta, axes: CapabilityAxes) -> Readiness:
    if meta.availability == "unsupported":
        return "not_applicable"

    if meta.availability == "optional_extra" and axes.installation == "missing":
        return "optional"

    if (
        meta.availability == "optional_extra"
        and axes.installation != "missing"
        and axes.configuration == "invalid"
    ):
        return "attention"

    if meta.availability == "optional_extra" and axes.installation == "unknown":
        return "attention"

    if axes.installation == "unknown" and meta.availability != "optional_extra":
        return "attention"

    if axes.configuration == "invalid" and meta.availability in {
        "built_in",
        "external_tool",
    }:
        return "blocked"

    if axes.configuration == "unconfigured" and meta.requires_config:
        return "attention"

    if axes.runtime == "unavailable" and meta.requires_runtime_proof:
        return "attention"

    if _axes_satisfied(meta, axes):
        return "ready"

    return "attention"


def apply_capability_presentation(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    handler = _PRESENTATION_BY_ID.get(meta.id)
    if handler is not None:
        return handler(meta, axes, readiness, ctx)
    return _presentation_default(meta, readiness)


def _presentation_default(
    meta: CapabilityMeta,
    readiness: Readiness,
) -> PresentationResult:
    if readiness == "optional":
        return (
            readiness,
            setup_ui.REASON_OPTIONAL_EXTRA_MISSING,
            _optional_install_hint(meta),
        )
    if readiness == "ready":
        return ("ready", "", "")
    return (
        readiness,
        setup_ui.REASON_UNKNOWN_PROBE,
        "",
    )


def _present_controlled_change(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del meta, readiness, ctx
    if axes.installation == "missing":
        return (
            "optional",
            setup_ui.REASON_REQUIRES_MCP_EXTRA,
            setup_ui.MCP_UV_INSTALL_HINT,
        )
    if axes.configuration == "unconfigured":
        return (
            "attention",
            setup_ui.REASON_CONTROLLED_CHANGE_NO_CLIENT,
            setup_ui.MCP_UV_INSTALL_HINT,
        )
    return (
        "attention",
        setup_ui.REASON_CONTROLLED_CHANGE_ATTENTION,
        setup_ui.MCP_UV_INSTALL_HINT,
    )


def _present_mcp_runtime(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del meta, readiness, ctx
    if axes.installation == "missing":
        return (
            "optional",
            setup_ui.REASON_REQUIRES_MCP_EXTRA,
            setup_ui.MCP_INSTALL_HINT,
        )
    return (
        "attention",
        setup_ui.REASON_MCP_INSTALLED_NOT_VERIFIED,
        setup_ui.MCP_UV_INSTALL_HINT,
    )


def _present_audit_and_intents(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del meta, readiness
    if axes.configuration == "invalid":
        return (
            "blocked",
            setup_ui.REASON_ANALYSIS_INVALID_CONFIG,
            "",
        )
    if not ctx.audit_enabled:
        return (
            "attention",
            setup_ui.REASON_AUDIT_DISABLED,
            "Enable audit_enabled in [tool.codeclone] to record controller events.",
        )
    if not ctx.audit_db_exists:
        return (
            "attention",
            setup_ui.REASON_AUDIT_DB_MISSING,
            "Run a governed workflow or enable audit to create the audit database.",
        )
    return (
        "attention",
        setup_ui.REASON_AUDIT_CONFIGURED,
        "",
    )


def _present_baseline(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del meta, readiness
    if axes.configuration == "configured":
        return ("ready", setup_ui.REASON_BASELINE_READY, "")
    if ctx.baseline_status is not None and ctx.baseline_status.name != "MISSING":
        return (
            "attention",
            setup_ui.REASON_BASELINE_UNTRUSTED,
            f"Regenerate or repair baseline at {ctx.baseline_path.name}.",
        )
    return (
        "attention",
        setup_ui.REASON_BASELINE_MISSING,
        f"Create a trusted baseline at {ctx.baseline_path.name}.",
    )


def _present_config_readiness(
    axes: CapabilityAxes,
    *,
    ready_reason: str,
    unconfigured_reason: str,
    unconfigured_action: str,
    invalid_action: str = "",
) -> PresentationResult:
    if axes.configuration == "invalid":
        return (
            "blocked",
            setup_ui.REASON_ANALYSIS_INVALID_CONFIG,
            invalid_action,
        )
    if axes.configuration == "unconfigured":
        return (
            "attention",
            unconfigured_reason,
            unconfigured_action,
        )
    return ("ready", ready_reason, "")


def _present_analysis(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del meta, readiness, ctx
    return _present_config_readiness(
        axes,
        ready_reason=setup_ui.REASON_ANALYSIS_READY,
        unconfigured_reason=setup_ui.REASON_ANALYSIS_UNCONFIGURED,
        unconfigured_action="Add a [tool.codeclone] section to pyproject.toml.",
        invalid_action="Fix tool.codeclone entries in pyproject.toml.",
    )


def _present_engineering_memory(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del meta, axes, readiness
    report = ctx.memory_report
    if report is not None and report.db_exists and report.record_count > 0:
        return ("ready", setup_ui.REASON_MEMORY_READY, "")
    return (
        "attention",
        setup_ui.REASON_MEMORY_EMPTY,
        "Run codeclone memory init after analysis to populate Engineering Memory.",
    )


def _present_reports(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del meta, axes, readiness, ctx
    return ("ready", setup_ui.REASON_REPORTS_READY, "")


def _present_semantic_retrieval(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del ctx
    if axes.installation == "missing":
        return (
            "optional",
            setup_ui.REASON_SEMANTIC_OPTIONAL,
            "uv sync --extra semantic-local",
        )
    return _presentation_default(meta, readiness)


def _present_coverage_evidence(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del ctx
    if axes.installation == "missing":
        return (
            "optional",
            setup_ui.REASON_COVERAGE_OPTIONAL,
            "uv sync --extra coverage-xml",
        )
    return _presentation_default(meta, readiness)


def _present_analytics_cockpit(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del ctx
    if axes.installation == "missing":
        status = check_capability("full")
        return (
            "optional",
            setup_ui.REASON_ANALYTICS_OPTIONAL,
            install_hint(status.missing_packages),
        )
    return _presentation_default(meta, readiness)


def _present_ci_policy(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del meta, readiness, ctx
    return _present_config_readiness(
        axes,
        ready_reason=setup_ui.REASON_CI_READY,
        unconfigured_reason=setup_ui.REASON_CI_BASELINE_ATTENTION,
        unconfigured_action="Ensure baseline trust before enabling CI gates.",
    )


def _present_github_workflow(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del ctx
    if axes.configuration == "unconfigured":
        return (
            "attention",
            setup_ui.REASON_GITHUB_WORKFLOW_MISSING,
            "Add a GitHub Actions workflow that runs codeclone in CI.",
        )
    return _presentation_default(meta, readiness)


def _present_pre_commit_hook(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del ctx
    if axes.configuration == "unconfigured":
        return (
            "attention",
            setup_ui.REASON_PRE_COMMIT_MISSING,
            "Add a pre-commit hook entry for codeclone.",
        )
    return _presentation_default(meta, readiness)


def _present_workspace_hygiene(
    meta: CapabilityMeta,
    axes: CapabilityAxes,
    readiness: Readiness,
    ctx: DiscoverContext,
) -> PresentationResult:
    del meta, readiness, ctx
    if axes.configuration == "configured":
        return ("ready", setup_ui.REASON_WORKSPACE_HYGIENE_READY, "")
    tip = gitignore_codeclone_cache_tip_payload()
    return (
        "attention",
        setup_ui.REASON_WORKSPACE_HYGIENE,
        str(tip.get("message", "")),
    )


_PRESENTATION_BY_ID: dict[str, PresentationHandler] = {
    "analysis": _present_analysis,
    "analytics_cockpit": _present_analytics_cockpit,
    "audit_and_intents": _present_audit_and_intents,
    "baseline": _present_baseline,
    "ci_policy": _present_ci_policy,
    "controlled_change": _present_controlled_change,
    "coverage_evidence": _present_coverage_evidence,
    "engineering_memory": _present_engineering_memory,
    "github_workflow": _present_github_workflow,
    "mcp_runtime": _present_mcp_runtime,
    "pre_commit_hook": _present_pre_commit_hook,
    "reports": _present_reports,
    "semantic_retrieval": _present_semantic_retrieval,
    "workspace_hygiene": _present_workspace_hygiene,
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


def _axes_satisfied(meta: CapabilityMeta, axes: CapabilityAxes) -> bool:
    if axes.installation == "unknown":
        return False
    if axes.configuration == "invalid":
        return False
    if meta.requires_config and axes.configuration == "unconfigured":
        return False
    return not (meta.requires_runtime_proof and axes.runtime == "unavailable")


__all__ = ["compute_maturity", "derive_readiness", "finalize_capabilities"]
