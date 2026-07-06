"""Deterministic review-unit decomposition from surface hints."""

from __future__ import annotations

import shlex
from typing import Any

from review_kit.git_evidence import diff_stats_for_paths
from review_kit.policy import RISK_ORDER, contract_owner_paths, surface_catalog
from review_kit.vectors import activate_vectors

_TIER_COST = {"haiku": 1, "sonnet": 3, "opus": 8}


def reviewer_tier(risk: str, profile: str, policy: dict[str, Any]) -> str:
    profiles = policy.get("review_profiles", {})
    spec = profiles.get(profile, {}) if isinstance(profiles, dict) else {}
    if not isinstance(spec, dict):
        spec = {}
    if risk == "critical":
        if profile == "thorough":
            return str(spec.get("high_risk", "opus"))
        return str(spec.get("critical_escalation", "opus"))
    if risk == "high":
        return str(spec.get("high_risk", "sonnet"))
    if risk == "medium":
        return str(spec.get("medium_risk", "sonnet"))
    return str(spec.get("low_risk", "haiku"))


def format_diff_command(base_sha: str, head_sha: str, paths: list[str]) -> str:
    quoted_paths = " ".join(shlex.quote(path) for path in paths)
    return f"git diff --find-renames {base_sha} {head_sha} -- {quoted_paths}".rstrip()


def _surface_stats(
    paths: list[str], file_items: list[dict[str, Any]]
) -> dict[str, int]:
    path_set = set(paths)
    files = 0
    for item in file_items:
        p = str(item.get("path", ""))
        o = str(item.get("old_path", ""))
        if p in path_set or o in path_set:
            files += 1
    return {"files": files, "paths": len(paths)}


def _should_skip_unit(
    *,
    risk: str,
    stats: dict[str, int],
    policy: dict[str, Any],
) -> bool:
    churn = policy.get("churn_skip", {})
    if not isinstance(churn, dict) or not churn.get("enabled", False):
        return False
    if risk in {"critical", "high"}:
        return False
    max_lines = int(churn.get("max_changed_lines", 20))
    max_files = int(churn.get("max_changed_files", 2))
    changed_lines = stats.get("insertions", 0) + stats.get("deletions", 0)
    return changed_lines <= max_lines and stats.get("files", 0) <= max_files


def build_review_units(
    *,
    policy: dict[str, Any],
    base_sha: str,
    head_sha: str,
    surface_hints: dict[str, list[str]],
    files: list[dict[str, Any]],
    classification: dict[str, bool],
    profile: str,
    repo_root: Any,
    contract_briefs: dict[str, str],
    verification_plan: list[dict[str, str]],
) -> list[dict[str, Any]]:
    catalog = surface_catalog(policy)
    touched = []
    for paths in surface_hints.values():
        touched.extend(paths)

    units: list[dict[str, Any]] = []
    ordered_surfaces = sorted(
        surface_hints.items(),
        key=lambda item: (
            RISK_ORDER.get(catalog.get(item[0], {}).get("default_risk", "medium"), 9),
            item[0],
        ),
    )

    for index, (surface, paths) in enumerate(ordered_surfaces, start=1):
        spec = catalog.get(surface, {})
        risk = str(spec.get("default_risk", "medium"))
        owner = str(spec.get("owner", ""))
        stats = diff_stats_for_paths(base_sha, head_sha, paths)
        surface_meta = _surface_stats(paths, files)
        vectors = activate_vectors(paths, policy, classification)
        tier = reviewer_tier(risk, profile, policy)
        context_paths = contract_owner_paths(policy, owner)
        unit_commands = [
            entry
            for entry in verification_plan
            if _command_applies_to_unit(entry, paths, surface)
        ]

        unit_id = f"R-{index:03d}"
        skip = _should_skip_unit(risk=risk, stats=stats, policy=policy)
        units.append(
            {
                "unit_id": unit_id,
                "primary_surface": surface,
                "owner": owner,
                "risk": risk,
                "reviewer_tier": tier,
                "skip_recommended": skip,
                "paths": paths,
                "context_paths": sorted(set(context_paths)),
                "stats": stats,
                "surface_file_count": surface_meta["files"],
                "activated_vectors": vectors["unit_vectors"],
                "unit_brief": {
                    "immutable_range": f"{base_sha}..{head_sha}",
                    "diff_command": format_diff_command(base_sha, head_sha, paths),
                    "contract_briefs": contract_briefs
                    if surface == "contracts_reports"
                    else {},
                    "mandatory_commands": unit_commands,
                    "proof_classes": ["contract", "invariants", "failures"],
                },
            }
        )

    return units


def path_matches_pattern(path: str, pattern: str) -> bool:
    if not pattern:
        return False
    from review_kit.paths import path_matches

    return path_matches(path, pattern)


def _command_applies_to_unit(
    entry: dict[str, str],
    paths: list[str],
    surface: str,
) -> bool:
    trigger = str(entry.get("trigger", ""))
    if not trigger:
        return False
    if trigger == "python_change":
        return any(path.endswith(".py") for path in paths)
    if trigger == "packaging_change":
        return "pyproject.toml" in paths or "uv.lock" in paths
    return any(path_matches_pattern(path, trigger) for path in paths)
