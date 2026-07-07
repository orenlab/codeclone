# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Read-only capability probes for setup readiness (§8.5)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Literal

from ..... import __version__
from .....analytics.capabilities import check_capability
from .....audit.reader import read_audit_summary
from .....audit.validation import DEFAULT_AUDIT_PATH, resolve_audit_path
from .....baseline import (
    Baseline,
    BaselineStatus,
    coerce_baseline_status,
    current_python_tag,
)
from .....baseline.metrics_baseline import probe_metrics_baseline_section
from .....config.memory import resolve_memory_config
from .....config.pyproject_loader import ConfigValidationError, load_pyproject_config
from .....contracts import DEFAULT_BASELINE_PATH, DEFAULT_MAX_BASELINE_SIZE_MB
from .....contracts.errors import BaselineValidationError
from .....memory.project import read_git_provenance, resolve_memory_db_path
from .....memory.status_report import build_memory_status_report
from .....paths.gitignore import repo_gitignore_covers_codeclone_cache
from ...startup import resolve_runtime_path_arg
from .capabilities import (
    SETUP_EXTRA_NAMES,
    CapabilityAxes,
    CapabilityMeta,
    DiscoverContext,
    ProbedCapability,
    sorted_capabilities,
)
from .rollup import compute_maturity, finalize_capabilities

InstallationAxis = Literal["installed", "missing", "unknown"]
ConfigurationAxis = Literal["configured", "unconfigured", "invalid", "not_required"]
RuntimeAxis = Literal["verified", "unavailable", "not_verified", "not_required"]


def build_discover_context(root_path: Path) -> DiscoverContext:
    """Build read-only discovery context for setup projections."""

    return _build_context(root_path.resolve())


def build_setup_snapshot(root_path: Path) -> dict[str, object]:
    return build_setup_snapshot_from_context(build_discover_context(root_path))


def build_setup_snapshot_from_context(ctx: DiscoverContext) -> dict[str, object]:
    probed = [_probe_capability(meta, ctx) for meta in sorted_capabilities()]
    capabilities = finalize_capabilities(probed, ctx)
    return {
        "schema_version": "1",
        "projection_kind": "setup_snapshot",
        "recomputation": True,
        "root": str(ctx.root_path),
        "head_commit": ctx.head_commit,
        "runtime": {
            "python_tag": current_python_tag(),
            "codeclone_version": __version__,
        },
        "install": {
            "base": "installed",
            "extras": ctx.install_extras,
        },
        "capabilities": capabilities,
        "maturity": compute_maturity(
            {str(item["id"]): item for item in capabilities},
            memory_db_exists=_memory_db_exists(ctx),
        ),
    }


def _build_context(root_path: Path) -> DiscoverContext:
    config_error: ConfigValidationError | None = None
    config: dict[str, object] = {}
    has_section = _tool_codeclone_section_present(root_path)
    try:
        config = load_pyproject_config(root_path)
    except ConfigValidationError as exc:
        config_error = exc

    baseline_raw = str(config.get("baseline", DEFAULT_BASELINE_PATH))
    baseline_path = resolve_runtime_path_arg(
        root_path=root_path,
        raw_path=baseline_raw,
        from_cli=False,
    )
    baseline_status = _probe_baseline_status(baseline_path)

    git = read_git_provenance(root_path)
    head_commit = git.head if git.available else None

    install_extras = {
        extra_name: ("installed" if _extra_installed(extra_name) else "missing")
        for extra_name in SETUP_EXTRA_NAMES
    }
    mcp_installed = install_extras["mcp"] == "installed"

    memory_report = None
    if config_error is None:
        memory_config = resolve_memory_config(root_path, pyproject_config=config)
        db_path = resolve_memory_db_path(root_path, memory_config)
        memory_report = build_memory_status_report(
            root_path=root_path,
            db_path=db_path,
            backend=memory_config.backend,
        )

    audit_enabled = bool(config.get("audit_enabled")) if config_error is None else False
    audit_db_exists = False
    audit_summary_events = 0
    if config_error is None and audit_enabled:
        try:
            audit_path = resolve_audit_path(
                root_path=root_path,
                value=str(config.get("audit_path", DEFAULT_AUDIT_PATH)),
            )
            audit_db_exists = audit_path.is_file()
            if audit_db_exists:
                summary = read_audit_summary(db_path=audit_path, limit=1)
                audit_summary_events = summary.total_events
        except OSError:
            audit_db_exists = False
        except Exception:
            audit_db_exists = False
            audit_summary_events = 0

    return DiscoverContext(
        root_path=root_path,
        config=config,
        config_error=config_error,
        has_codeclone_section=has_section,
        baseline_path=baseline_path,
        baseline_status=baseline_status,
        head_commit=head_commit,
        install_extras=install_extras,
        mcp_installed=mcp_installed,
        memory_report=memory_report,
        audit_enabled=audit_enabled,
        audit_db_exists=audit_db_exists,
        audit_summary_events=audit_summary_events,
        gitignore_covers_cache=repo_gitignore_covers_codeclone_cache(root_path),
        client_config_present=_client_config_present(root_path),
    )


def _probe_capability(meta: CapabilityMeta, ctx: DiscoverContext) -> ProbedCapability:
    probe_fn = _PROBE_BY_ID.get(meta.id, _probe_unknown)
    axes = probe_fn(ctx)
    axes.evidence.sort()
    return ProbedCapability(meta=meta, axes=axes)


def _probe_unknown(ctx: DiscoverContext) -> CapabilityAxes:
    del ctx
    return CapabilityAxes(
        installation="unknown",
        configuration="not_required",
        runtime="not_required",
        evidence=["probe:unknown:capability"],
    )


def _probe_analysis(ctx: DiscoverContext) -> CapabilityAxes:
    evidence: list[str] = ["probe:import:codeclone.core"]
    installation: InstallationAxis = "installed"
    try:
        if importlib.util.find_spec("codeclone.core") is None:
            installation = "unknown"
    except (ImportError, ModuleNotFoundError, ValueError):
        installation = "unknown"

    if ctx.config_error is not None:
        return CapabilityAxes(
            installation=installation,
            configuration="invalid",
            runtime="not_required",
            evidence=[*evidence, "probe:pyproject:tool.codeclone"],
        )

    if not ctx.has_codeclone_section:
        return CapabilityAxes(
            installation=installation,
            configuration="unconfigured",
            runtime="not_required",
            evidence=[*evidence, "probe:pyproject:tool.codeclone"],
        )

    return CapabilityAxes(
        installation=installation,
        configuration="configured",
        runtime="not_required",
        evidence=[*evidence, "probe:pyproject:tool.codeclone"],
    )


def _probe_baseline(ctx: DiscoverContext) -> CapabilityAxes:
    evidence = ["probe:path:baseline"]
    if ctx.baseline_path.is_symlink():
        return CapabilityAxes(
            installation="unknown",
            configuration="not_required",
            runtime="not_required",
            evidence=[*evidence, "probe:path:baseline:symlink"],
        )
    if not ctx.baseline_path.exists():
        return CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_required",
            evidence=[*evidence, "probe:path:baseline:missing"],
        )
    if ctx.baseline_status is None:
        # File present but could not be read (permissions / IO error): fail closed.
        return CapabilityAxes(
            installation="unknown",
            configuration="not_required",
            runtime="not_required",
            evidence=[*evidence, "probe:path:baseline:unreadable"],
        )
    if ctx.baseline_status is BaselineStatus.OK:
        return CapabilityAxes(
            installation="installed",
            configuration="configured",
            runtime="not_required",
            evidence=[*evidence, "probe:baseline:trust"],
        )

    # Present but untrusted/corrupt: attention (baseline never hard-blocks core
    # analysis), with the precise status carried on evidence for doctor output.
    return CapabilityAxes(
        installation="installed",
        configuration="unconfigured",
        runtime="not_required",
        evidence=[
            *evidence,
            "probe:baseline:trust",
            f"probe:baseline:status:{ctx.baseline_status.value}",
        ],
    )


def _probe_reports(ctx: DiscoverContext) -> CapabilityAxes:
    del ctx
    return CapabilityAxes(
        installation="installed",
        configuration="not_required",
        runtime="not_required",
        evidence=[],
    )


def _probe_mcp_runtime(ctx: DiscoverContext) -> CapabilityAxes:
    if ctx.mcp_installed:
        return CapabilityAxes(
            installation="installed",
            configuration="not_required",
            runtime="not_verified",
            evidence=["probe:find_spec:mcp"],
        )
    return CapabilityAxes(
        installation="missing",
        configuration="not_required",
        runtime="not_required",
        evidence=["probe:find_spec:mcp"],
    )


def _probe_controlled_change(ctx: DiscoverContext) -> CapabilityAxes:
    if not ctx.mcp_installed:
        return CapabilityAxes(
            installation="missing",
            configuration="not_required",
            runtime="not_required",
            evidence=["probe:find_spec:mcp"],
        )
    if ctx.client_config_present:
        return CapabilityAxes(
            installation="installed",
            configuration="configured",
            runtime="not_verified",
            evidence=["probe:find_spec:mcp", "probe:client:mcp_config"],
        )
    return CapabilityAxes(
        installation="installed",
        configuration="unconfigured",
        runtime="not_verified",
        evidence=["probe:find_spec:mcp", "probe:client:mcp_config:missing"],
    )


def _probe_audit_and_intents(ctx: DiscoverContext) -> CapabilityAxes:
    evidence = ["probe:audit:enabled"]
    if ctx.config_error is not None:
        return CapabilityAxes(
            installation="installed",
            configuration="invalid",
            runtime="not_required",
            evidence=evidence,
        )
    if not ctx.audit_enabled:
        return CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_required",
            evidence=evidence,
        )

    evidence.append("probe:audit:db")
    if not ctx.audit_db_exists:
        return CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_required",
            evidence=evidence,
        )

    evidence.append("probe:audit:summary")
    # DB present and enabled: distinguish a populated trail (runtime-verified) from
    # an empty one (configured but nothing recorded yet).
    has_events = ctx.audit_summary_events > 0
    runtime: RuntimeAxis = "verified" if has_events else "not_verified"
    return CapabilityAxes(
        installation="installed",
        configuration="configured",
        runtime=runtime,
        evidence=evidence,
    )


def _probe_engineering_memory(ctx: DiscoverContext) -> CapabilityAxes:
    evidence = ["probe:memory:status"]
    report = ctx.memory_report
    if report is None:
        # No report is only produced when pyproject config failed to load.
        return CapabilityAxes(
            installation="installed",
            configuration="invalid" if ctx.config_error else "unconfigured",
            runtime="not_verified",
            evidence=evidence,
        )
    if not report.db_exists:
        return CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_verified",
            evidence=evidence,
        )
    # Store present: verified only when it actually holds records.
    runtime: RuntimeAxis = "verified" if report.record_count > 0 else "not_verified"
    return CapabilityAxes(
        installation="installed",
        configuration="configured",
        runtime=runtime,
        evidence=[*evidence, "probe:memory:records"],
    )


def _probe_semantic_retrieval(ctx: DiscoverContext) -> CapabilityAxes:
    status = check_capability("embed")
    evidence = ["probe:capability:embed"]
    if not status.available:
        return CapabilityAxes(
            installation="missing",
            configuration="not_required",
            runtime="not_required",
            evidence=evidence,
        )

    report = ctx.memory_report
    if report is None or not report.db_exists:
        # Packages present but semantic retrieval needs a memory store to operate.
        return CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_verified",
            evidence=[*evidence, "probe:memory:store:missing"],
        )

    memory_config = resolve_memory_config(ctx.root_path, pyproject_config=ctx.config)
    configuration: ConfigurationAxis = (
        "configured" if memory_config.semantic.enabled else "unconfigured"
    )
    return CapabilityAxes(
        installation="installed",
        configuration=configuration,
        runtime="not_verified",
        evidence=[*evidence, "probe:memory:semantic"],
    )


def _probe_coverage_evidence(ctx: DiscoverContext) -> CapabilityAxes:
    del ctx
    if importlib.util.find_spec("defusedxml") is None:
        return CapabilityAxes(
            installation="missing",
            configuration="not_required",
            runtime="not_required",
            evidence=["probe:find_spec:defusedxml"],
        )
    return CapabilityAxes(
        installation="installed",
        configuration="not_required",
        runtime="not_verified",
        evidence=["probe:find_spec:defusedxml"],
    )


def _probe_analytics_cockpit(ctx: DiscoverContext) -> CapabilityAxes:
    del ctx
    status = check_capability("full")
    evidence = ["probe:capability:analytics:full"]
    if status.available:
        return CapabilityAxes(
            installation="installed",
            configuration="not_required",
            runtime="not_verified",
            evidence=evidence,
        )
    return CapabilityAxes(
        installation="missing",
        configuration="not_required",
        runtime="not_required",
        evidence=evidence,
    )


def _probe_ci_policy(ctx: DiscoverContext) -> CapabilityAxes:
    evidence = ["probe:pyproject:ci_flags"]
    if ctx.config_error is not None:
        return CapabilityAxes(
            installation="installed",
            configuration="invalid",
            runtime="not_required",
            evidence=evidence,
        )

    ci_like = any(
        bool(ctx.config.get(flag))
        for flag in ("ci", "fail_on_new", "fail_on_new_metrics")
    )
    if not ci_like:
        # No CI gating flags set. This is an opt-in team feature, so report it as
        # not-yet-configured (attention) rather than claiming it is "configured".
        return CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_required",
            evidence=[*evidence, "probe:pyproject:ci_flags:absent"],
        )

    if ctx.baseline_status is not BaselineStatus.OK:
        return CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_required",
            evidence=[*evidence, "probe:baseline:trust"],
        )

    metrics_probe = probe_metrics_baseline_section(ctx.baseline_path)
    if metrics_probe.has_metrics_section and metrics_probe.payload is None:
        return CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_required",
            evidence=[*evidence, "probe:metrics_baseline:section"],
        )

    return CapabilityAxes(
        installation="installed",
        configuration="configured",
        runtime="not_required",
        evidence=evidence,
    )


def _probe_github_workflow(ctx: DiscoverContext) -> CapabilityAxes:
    workflows_dir = ctx.root_path / ".github" / "workflows"
    evidence = ["probe:file:.github/workflows"]
    if not workflows_dir.is_dir():
        return CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_required",
            evidence=[*evidence, "probe:file:.github/workflows:missing"],
        )
    markers = ("codeclone", "orenlab/codeclone")
    saw_unreadable = False
    for path in sorted(workflows_dir.glob("*")):
        if path.suffix not in {".yml", ".yaml"}:
            continue
        text, existed = _safe_read_text(path)
        if text is None:
            saw_unreadable = saw_unreadable or existed
            continue
        lowered = text.lower()
        if any(marker in lowered for marker in markers):
            return CapabilityAxes(
                installation="installed",
                configuration="configured",
                runtime="not_required",
                evidence=[*evidence, f"probe:file:{path.name}"],
            )
    if saw_unreadable:
        return CapabilityAxes(
            installation="unknown",
            configuration="not_required",
            runtime="not_required",
            evidence=[*evidence, "probe:file:.github/workflows:unreadable"],
        )
    return CapabilityAxes(
        installation="installed",
        configuration="unconfigured",
        runtime="not_required",
        evidence=[*evidence, "probe:file:.github/workflows:not_found"],
    )


def _probe_pre_commit_hook(ctx: DiscoverContext) -> CapabilityAxes:
    config_path = ctx.root_path / ".pre-commit-config.yaml"
    evidence = ["probe:file:.pre-commit-config.yaml"]
    text, existed = _safe_read_text(config_path)
    if text is None:
        if existed:
            return CapabilityAxes(
                installation="unknown",
                configuration="not_required",
                runtime="not_required",
                evidence=[*evidence, "probe:file:.pre-commit-config.yaml:unreadable"],
            )
        return CapabilityAxes(
            installation="installed",
            configuration="unconfigured",
            runtime="not_required",
            evidence=[*evidence, "probe:file:.pre-commit-config.yaml:missing"],
        )
    if "codeclone" in text.lower():
        return CapabilityAxes(
            installation="installed",
            configuration="configured",
            runtime="not_required",
            evidence=evidence,
        )
    return CapabilityAxes(
        installation="installed",
        configuration="unconfigured",
        runtime="not_required",
        evidence=[*evidence, "probe:file:.pre-commit-config.yaml:not_found"],
    )


def _probe_workspace_hygiene(ctx: DiscoverContext) -> CapabilityAxes:
    evidence = ["probe:gitignore:codeclone_cache"]
    if ctx.gitignore_covers_cache:
        return CapabilityAxes(
            installation="installed",
            configuration="configured",
            runtime="not_required",
            evidence=evidence,
        )
    return CapabilityAxes(
        installation="installed",
        configuration="unconfigured",
        runtime="not_required",
        evidence=[*evidence, "probe:gitignore:codeclone_cache:missing"],
    )


_PROBE_BY_ID = {
    "analysis": _probe_analysis,
    "baseline": _probe_baseline,
    "reports": _probe_reports,
    "mcp_runtime": _probe_mcp_runtime,
    "controlled_change": _probe_controlled_change,
    "audit_and_intents": _probe_audit_and_intents,
    "engineering_memory": _probe_engineering_memory,
    "semantic_retrieval": _probe_semantic_retrieval,
    "coverage_evidence": _probe_coverage_evidence,
    "analytics_cockpit": _probe_analytics_cockpit,
    "ci_policy": _probe_ci_policy,
    "github_workflow": _probe_github_workflow,
    "pre_commit_hook": _probe_pre_commit_hook,
    "workspace_hygiene": _probe_workspace_hygiene,
}


def _probe_baseline_status(baseline_path: Path) -> BaselineStatus | None:
    if not baseline_path.exists():
        return BaselineStatus.MISSING
    baseline = Baseline(baseline_path)
    try:
        baseline.load(
            max_size_bytes=DEFAULT_MAX_BASELINE_SIZE_MB * 1024 * 1024,
        )
        baseline.verify_compatibility(current_python_tag=current_python_tag())
    except BaselineValidationError as exc:
        return coerce_baseline_status(exc.status)
    except OSError:
        # Unreadable file (permissions / IO): unknown, not "invalid JSON".
        return None
    return BaselineStatus.OK


def _extra_installed(extra_name: str) -> bool:
    if extra_name == "mcp":
        return importlib.util.find_spec("mcp") is not None
    if extra_name == "coverage-xml":
        return importlib.util.find_spec("defusedxml") is not None
    if extra_name == "perf":
        return importlib.util.find_spec("psutil") is not None
    if extra_name == "token-bench":
        return importlib.util.find_spec("tiktoken") is not None
    if extra_name == "analytics":
        return check_capability("full").available
    if extra_name == "semantic-local":
        return check_capability("embed").available
    if extra_name == "semantic-fastembed":
        return importlib.util.find_spec("fastembed") is not None
    if extra_name == "semantic-lancedb":
        return importlib.util.find_spec("lancedb") is not None
    return False


def _tool_codeclone_section_present(root_path: Path) -> bool:
    config_path = root_path / "pyproject.toml"
    if not config_path.is_file():
        return False
    if sys.version_info >= (3, 11):
        import tomllib

        loader = tomllib.load
    else:
        try:
            tomli_module = importlib.import_module("tomli")
        except ModuleNotFoundError:
            return False
        load_fn = getattr(tomli_module, "load", None)
        if not callable(load_fn):
            return False
        loader = load_fn

    try:
        with config_path.open("rb") as handle:
            payload = loader(handle)
    except OSError:
        return False
    except ValueError:
        return False

    if not isinstance(payload, dict):
        return False
    tool_obj = payload.get("tool")
    if not isinstance(tool_obj, dict):
        return False
    return "codeclone" in tool_obj


def _client_config_present(root_path: Path) -> bool:
    for candidate in (root_path / ".cursor" / "mcp.json", root_path / ".mcp.json"):
        if candidate.is_file() and not candidate.is_symlink():
            return True
    vscode_settings = root_path / ".vscode" / "settings.json"
    text, _existed = _safe_read_text(vscode_settings)
    if text is None:
        return False
    lowered = text.lower()
    # Match the MCP server key names, not any incidental "codeclone" substring
    # (a path or comment) that would falsely mark the client as configured.
    return "codeclone-mcp" in lowered or '"codeclone"' in lowered


def _safe_read_text(path: Path) -> tuple[str | None, bool]:
    """Read a regular file under the repo root without following symlinks.

    Returns ``(text, existed)``. ``text`` is ``None`` when the path is absent, is
    a symlink (refused), or cannot be read; ``existed`` is ``True`` whenever the
    path is present on disk (including a refused symlink or an unreadable file),
    which lets callers distinguish "missing" from "present but unknown".
    """

    if path.is_symlink():
        return None, True
    if not path.is_file():
        return None, False
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with open(fd, encoding="utf-8") as handle:
            return handle.read(), True
    except OSError:
        return None, True


def _memory_db_exists(ctx: DiscoverContext) -> bool:
    report = ctx.memory_report
    return bool(report is not None and report.db_exists)


__all__ = [
    "build_discover_context",
    "build_setup_snapshot",
    "build_setup_snapshot_from_context",
]
